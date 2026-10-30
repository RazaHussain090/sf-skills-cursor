const { execFile } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const targetOrg = process.env.DELIVERY_TARGET_ORG || "delivery-agent";
const sfCommand = process.platform === "win32" ? "sf.cmd" : "sf";

const tools = [
  {
    name: "pull_delivery",
    description: "Pull one delivery, including status, latest GPS point, and the navigation link while it is in transit.",
    inputSchema: {
      type: "object",
      properties: {
        deliveryNumber: {
          type: "string",
          description: "Delivery number, for example DLV-0004.",
        },
      },
      required: ["deliveryNumber"],
    },
  },
  {
    name: "pull_in_transit",
    description: "Pull every delivery that is In Transit and the latest GPS point reported by the driver device.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
];

let buffer = Buffer.alloc(0);

process.stdin.on("data", (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  for (;;) {
    const headerEnd = buffer.indexOf("\r\n\r\n");
    if (headerEnd === -1) {
      return;
    }
    const header = buffer.slice(0, headerEnd).toString("utf8");
    const match = header.match(/Content-Length:\s*(\d+)/i);
    if (!match) {
      buffer = buffer.slice(headerEnd + 4);
      continue;
    }
    const length = Number(match[1]);
    const bodyStart = headerEnd + 4;
    if (buffer.length < bodyStart + length) {
      return;
    }
    const body = buffer.slice(bodyStart, bodyStart + length).toString("utf8");
    buffer = buffer.slice(bodyStart + length);
    handle(JSON.parse(body));
  }
});

function send(message) {
  const json = JSON.stringify(message);
  process.stdout.write(`Content-Length: ${Buffer.byteLength(json, "utf8")}\r\n\r\n${json}`);
}

function handle(message) {
  if (message.id === undefined || message.id === null) {
    return;
  }
  if (message.method === "initialize") {
    send({
      jsonrpc: "2.0",
      id: message.id,
      result: {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "delivery-pull", version: "1.0.0" },
      },
    });
    return;
  }
  if (message.method === "tools/list") {
    send({ jsonrpc: "2.0", id: message.id, result: { tools } });
    return;
  }
  if (message.method === "tools/call") {
    callTool(message);
    return;
  }
  send({
    jsonrpc: "2.0",
    id: message.id,
    error: { code: -32601, message: "Method not found" },
  });
}

async function callTool(message) {
  const name = message.params && message.params.name;
  const args = (message.params && message.params.arguments) || {};
  try {
    const text = name === "pull_delivery"
      ? await pullDelivery(args.deliveryNumber)
      : name === "pull_in_transit"
        ? await pullInTransit()
        : null;
    if (text === null) {
      send({
        jsonrpc: "2.0",
        id: message.id,
        error: { code: -32602, message: "Unknown tool" },
      });
      return;
    }
    send({
      jsonrpc: "2.0",
      id: message.id,
      result: { content: [{ type: "text", text }] },
    });
  } catch (error) {
    send({
      jsonrpc: "2.0",
      id: message.id,
      result: {
        isError: true,
        content: [{ type: "text", text: error.message }],
      },
    });
  }
}

function pullDelivery(deliveryNumber) {
  if (!deliveryNumber) {
    return Promise.reject(new Error("deliveryNumber is required."));
  }
  return sfGet(`/services/apexrest/delivery/v1/${encodeURIComponent(deliveryNumber)}`);
}

function pullInTransit() {
  return sfGet("/services/apexrest/delivery/v1/in-transit");
}

function quoteForCmd(value) {
  if (value.length === 0 || /[\s"&|<>^%]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function sfGet(urlPath) {
  const args = ["api", "request", "rest", urlPath, "--method", "GET", "--target-org", targetOrg];
  const command = process.platform === "win32" ? process.env.ComSpec || "cmd.exe" : sfCommand;
  const commandArgs =
    process.platform === "win32" ? ["/d", "/s", "/c", ["sf", ...args].map(quoteForCmd).join(" ")] : args;
  return new Promise((resolve, reject) => {
    execFile(
      command,
      commandArgs,
      { windowsHide: true, maxBuffer: 2 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error((stderr || stdout || error.message).trim()));
          return;
        }
        resolve(stdout.trim());
      }
    );
  });
}

process.on("uncaughtException", (error) => {
  const file = path.join(os.tmpdir(), "delivery-pull-mcp-error.log");
  fs.appendFileSync(file, `${error.stack}\n`);
});
