@RestResource(urlMapping='/delivery/v1/*')
global with sharing class DeliveryRest {
    @HttpGet
    global static void pull() {
        write(route(false));
    }

    @HttpPost
    global static void push() {
        write(route(true));
    }

    private static DeliveryTracking.Result route(Boolean isPost) {
        List<String> parts = pathParts();
        if (parts.isEmpty()) {
            return new DeliveryTracking.Result(400, new Map<String, String>{
                'error' => 'Use /delivery/v1/{deliveryNumber} or /delivery/v1/in-transit.'
            });
        }
        if (!isPost && parts.size() == 1 && parts[0] == 'in-transit') {
            return DeliveryTracking.pullInTransit();
        }
        if (!isPost && parts.size() == 1) {
            return DeliveryTracking.pullByNumber(parts[0]);
        }
        if (isPost && parts.size() == 2 && parts[1] == 'location') {
            Map<String, Object> body = readBody();
            return DeliveryTracking.recordLocation(
                parts[0],
                decimalValue(body.get('latitude')),
                decimalValue(body.get('longitude'))
            );
        }
        if (isPost && parts.size() == 2 && parts[1] == 'status') {
            Map<String, Object> body = readBody();
            Object status = body.get('status');
            return DeliveryTracking.markStatus(parts[0], status == null ? null : String.valueOf(status));
        }
        return new DeliveryTracking.Result(404, new Map<String, String>{
            'error' => 'Unknown delivery route.'
        });
    }

    private static void write(DeliveryTracking.Result result) {
        RestResponse response = RestContext.response;
        response.statusCode = result.statusCode;
        response.addHeader('Content-Type', 'application/json');
        response.responseBody = Blob.valueOf(JSON.serialize(result.body));
    }

    private static List<String> pathParts() {
        String uri = RestContext.request.requestURI == null ? '' : RestContext.request.requestURI;
        Integer marker = uri.indexOf('/delivery/v1/');
        if (marker < 0) {
            return new List<String>();
        }
        String tail = uri.substring(marker + '/delivery/v1/'.length());
        if (tail.endsWith('/')) {
            tail = tail.substring(0, tail.length() - 1);
        }
        if (String.isBlank(tail)) {
            return new List<String>();
        }
        return tail.split('/');
    }

    private static Map<String, Object> readBody() {
        Blob raw = RestContext.request.requestBody;
        if (raw == null || String.isBlank(raw.toString())) {
            return new Map<String, Object>();
        }
        Object parsed = JSON.deserializeUntyped(raw.toString());
        if (parsed instanceof Map<String, Object>) {
            return (Map<String, Object>) parsed;
        }
        return new Map<String, Object>();
    }

    private static Decimal decimalValue(Object value) {
        if (value == null || String.isBlank(String.valueOf(value))) {
            return null;
        }
        return Decimal.valueOf(String.valueOf(value));
    }
}
