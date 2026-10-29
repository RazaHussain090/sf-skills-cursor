#!/bin/bash
# Regression gate for W-24156705: the Platform-MCP gateway can report an
# expired per-org JWT as 404 instead of 401. The proxy must re-mint once and
# retry, while allowing a second 404 to reach the existing inactive classifier.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../../../../.." && pwd)"
PROXY="$REPO/plugins/builder/salesforce-development/scripts/sf-mcp-proxy.bundled.js"
NODE_BIN="${NODE_BIN:-node}"

echo "mcp-proxy JWT refresh — $("$NODE_BIN" -v)"

"$NODE_BIN" - "$PROXY" <<'NODE'
const assert = require('assert');
const { classifyUpstream, postWithJwtRefresh } = require(process.argv[2]);

async function exercise(firstStatus, secondStatus, options = {}) {
  const calls = [];
  let mintCount = 0;
  const session = options.session || {
    upstreamUrl: 'https://example.invalid/platform/mcp',
    jwt: 'stale-jwt',
    connection: { marker: 'connection' },
  };
  const statuses = [firstStatus, secondStatus];
  const bodies = options.bodies || statuses.map((status) => `HTTP ${status}`);
  const response = (status, body) => ({
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => name.toLowerCase() === 'mcp-session-id' ? options.sessionId || null : null },
    text: async () => body,
  });
  const result = await postWithJwtRefresh(session, 'session-123', '{"jsonrpc":"2.0"}', {
    postUpstream: async (url, jwt, sessionId, body) => {
      calls.push({ url, jwt, sessionId, body });
      return response(statuses.shift(), bodies.shift());
    },
    mintJwt: async (connection) => {
      assert.strictEqual(connection, session.connection);
      mintCount += 1;
      return 'fresh-jwt';
    },
    now: options.now,
    cooldownMs: options.cooldownMs,
  });
  return { calls, mintCount, result, session };
}

(async () => {
  const stale404 = await exercise(404, 200);
  assert.strictEqual(stale404.mintCount, 1, '404 re-mints exactly once');
  assert.strictEqual(stale404.calls.length, 2, '404 retries exactly once');
  assert.strictEqual(stale404.calls[0].jwt, 'stale-jwt');
  assert.strictEqual(stale404.calls[1].jwt, 'fresh-jwt');
  assert.strictEqual(stale404.session.jwt, 'fresh-jwt');
  assert.strictEqual(stale404.result.status, 200);

  const inactiveBody = 'Server definition not found for this org';
  const cooldownMs = 60_000;
  const inactive404 = await exercise(404, 404, {
    bodies: ['first 404', inactiveBody],
    now: () => 1_000,
    cooldownMs,
  });
  assert.strictEqual(inactive404.mintCount, 1, 'persistent 404 still re-mints only once');
  assert.strictEqual(inactive404.calls.length, 2, 'persistent 404 does not loop');
  assert.strictEqual(inactive404.result.status, 404, 'second 404 reaches normal classifier');
  assert.strictEqual(inactive404.session.next404RefreshAt, 61_000, 'persistent 404 starts the cooldown');
  assert.strictEqual(inactive404.result.ok, false, 'returned response preserves the ok property');
  assert.strictEqual(inactive404.result.headers.get('mcp-session-id'), null, 'returned response preserves headers');
  const actualInactiveBody = await inactive404.result.text();
  assert.strictEqual(actualInactiveBody, inactiveBody, 'second response body survives the retry round-trip');
  assert.strictEqual(
    classifyUpstream(inactive404.result.status, actualInactiveBody),
    'inactive',
    'persistent server-definition 404 retains the inactive classification',
  );

  const coolingDown = await exercise(404, 200, {
    session: inactive404.session,
    bodies: [inactiveBody, 'unused'],
    now: () => 2_000,
    cooldownMs,
  });
  assert.strictEqual(coolingDown.mintCount, 0, 'inactive server does not re-mint during the cooldown');
  assert.strictEqual(coolingDown.calls.length, 1, 'inactive server is not retried during the cooldown');
  assert.strictEqual(
    classifyUpstream(coolingDown.result.status, await coolingDown.result.text()),
    'inactive',
    'cooldown still preserves the inactive response and classifier input',
  );

  const cooldownExpired = await exercise(404, 200, {
    session: inactive404.session,
    bodies: ['stale after activation', '{"jsonrpc":"2.0","result":{}}'],
    now: () => 61_000,
    cooldownMs,
  });
  assert.strictEqual(cooldownExpired.mintCount, 1, '404 re-mints after the cooldown expires');
  assert.strictEqual(cooldownExpired.calls.length, 2, '404 retries after the cooldown expires');
  assert.strictEqual(cooldownExpired.result.status, 200, 'server can recover after cooldown');
  assert.strictEqual(cooldownExpired.session.next404RefreshAt, 0, 'successful retry clears the cooldown');

  const unauthorized = await exercise(401, 200);
  assert.strictEqual(unauthorized.mintCount, 1, 'existing 401 refresh remains intact');
  assert.strictEqual(unauthorized.calls.length, 2, '401 retries exactly once');

  const serverError = await exercise(500, 200);
  assert.strictEqual(serverError.mintCount, 0, 'unrelated statuses do not re-mint');
  assert.strictEqual(serverError.calls.length, 1, 'unrelated statuses are not retried');
  assert.strictEqual(serverError.result.status, 500);

  console.log('PASS (404/401 refresh once; inactive 404 retries are cooldown-bounded)');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
NODE
