public with sharing class DeliveryTracking {
    public class Result {
        public Integer statusCode;
        public Object body;

        public Result(Integer statusCode, Object body) {
            this.statusCode = statusCode;
            this.body = body;
        }
    }

    public static Result pullByNumber(String deliveryNumber) {
        Delivery__c delivery = find(deliveryNumber);
        if (delivery == null) {
            return new Result(404, error('No delivery found for ' + normalize(deliveryNumber) + '.'));
        }
        return new Result(200, toPayload(delivery));
    }

    public static Result pullInTransit() {
        List<Object> rows = new List<Object>();
        for (Delivery__c delivery : [
            SELECT Name, Customer_Name__c, Status__c, Dropoff_Address__c,
                Driver_Location__Latitude__s, Driver_Location__Longitude__s, Location_Updated_On__c, Driver__r.Name
            FROM Delivery__c
            WHERE Status__c = 'In Transit'
            ORDER BY Name
        ]) {
            rows.add(toPayload(delivery));
        }
        return new Result(200, rows);
    }

    public static Result recordLocation(String deliveryNumber, Decimal latitude, Decimal longitude) {
        String coordinateError = validateCoordinates(latitude, longitude);
        if (coordinateError != null) {
            return new Result(400, error(coordinateError));
        }
        Delivery__c delivery = find(deliveryNumber);
        if (delivery == null) {
            return new Result(404, error('No delivery found for ' + normalize(deliveryNumber) + '.'));
        }
        if (delivery.Status__c != 'In Transit') {
            return new Result(409, error('Location is only accepted while the delivery is In Transit.'));
        }

        Datetime recordedAt = System.now();
        insert new Delivery_Location__c(
            Delivery__c = delivery.Id,
            Latitude__c = latitude,
            Longitude__c = longitude,
            Recorded_At__c = recordedAt
        );
        delivery.Driver_Location__Latitude__s = latitude;
        delivery.Driver_Location__Longitude__s = longitude;
        delivery.Location_Updated_On__c = recordedAt;
        update delivery;
        if (delivery.Driver__c != null) {
            update new Driver__c(
                Id = delivery.Driver__c,
                Current_Location__Latitude__s = latitude,
                Current_Location__Longitude__s = longitude,
                Location_Updated_On__c = recordedAt
            );
        }
        return pullByNumber(delivery.Name);
    }

    public static Result markStatus(String deliveryNumber, String status) {
        if (status != 'Attempted' && status != 'Delivered') {
            return new Result(400, error('Status must be Attempted or Delivered.'));
        }
        Delivery__c delivery = find(deliveryNumber);
        if (delivery == null) {
            return new Result(404, error('No delivery found for ' + normalize(deliveryNumber) + '.'));
        }
        if (status == 'Attempted' && delivery.Status__c != 'In Transit') {
            return new Result(409, error('Attempted is only allowed from In Transit.'));
        }
        if (status == 'Delivered' && delivery.Status__c != 'In Transit' && delivery.Status__c != 'Attempted') {
            return new Result(409, error('Delivered is only allowed from In Transit or Attempted.'));
        }

        delivery.Status__c = status;
        if (status == 'Attempted' && delivery.Attempted_On__c == null) {
            delivery.Attempted_On__c = System.now();
        }
        if (status == 'Delivered' && delivery.Delivered_On__c == null) {
            delivery.Delivered_On__c = System.now();
        }
        update delivery;
        return pullByNumber(delivery.Name);
    }

    public static void publishStatusChanges(List<Delivery__c> changed) {
        List<Delivery_Notification__e> notices = new List<Delivery_Notification__e>();
        for (Delivery__c delivery : changed) {
            notices.add(buildNotice(delivery, delivery.Driver_Location__Latitude__s, delivery.Driver_Location__Longitude__s, delivery.Name + ' is now ' + delivery.Status__c));
        }
        publish(notices);
    }

    public static void publishLocationPings(List<Delivery_Location__c> pings) {
        Set<Id> deliveryIds = new Set<Id>();
        for (Delivery_Location__c ping : pings) {
            deliveryIds.add(ping.Delivery__c);
        }
        Map<Id, Delivery__c> deliveries = new Map<Id, Delivery__c>([
            SELECT Name, Status__c, Dropoff_Address__c, Driver_Location__Latitude__s, Driver_Location__Longitude__s
            FROM Delivery__c
            WHERE Id IN :deliveryIds
        ]);
        List<Delivery_Notification__e> notices = new List<Delivery_Notification__e>();
        for (Delivery_Location__c ping : pings) {
            Delivery__c delivery = deliveries.get(ping.Delivery__c);
            if (delivery == null) {
                continue;
            }
            notices.add(buildNotice(delivery, ping.Latitude__c, ping.Longitude__c, 'Location updated for ' + delivery.Name));
        }
        publish(notices);
    }

    private static Delivery__c find(String deliveryNumber) {
        String normalized = normalize(deliveryNumber);
        if (String.isBlank(normalized)) {
            return null;
        }
        List<Delivery__c> rows = [
            SELECT Name, Customer_Name__c, Status__c, Dropoff_Address__c, Delivered_On__c, Attempted_On__c, Driver__c,
                Driver_Location__Latitude__s, Driver_Location__Longitude__s, Location_Updated_On__c, Driver__r.Name
            FROM Delivery__c
            WHERE Name = :normalized
            LIMIT 1
        ];
        return rows.isEmpty() ? null : rows[0];
    }

    private static String normalize(String deliveryNumber) {
        if (String.isBlank(deliveryNumber)) {
            return null;
        }
        String trimmed = deliveryNumber.trim();
        if (trimmed.toLowerCase().startsWith('dlv-')) {
            return trimmed.toUpperCase();
        }
        return trimmed;
    }

    private static String validateCoordinates(Decimal latitude, Decimal longitude) {
        if (latitude == null || longitude == null) {
            return 'Latitude and longitude are required.';
        }
        if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
            return 'Latitude must be between -90 and 90, and longitude between -180 and 180.';
        }
        return null;
    }

    private static Map<String, Object> toPayload(Delivery__c delivery) {
        String navigationUrl = navigationUrl(delivery, delivery.Driver_Location__Latitude__s, delivery.Driver_Location__Longitude__s);
        return new Map<String, Object>{
            'deliveryNumber' => delivery.Name,
            'customerName' => delivery.Customer_Name__c,
            'status' => delivery.Status__c,
            'driverName' => delivery.Driver__r == null ? null : delivery.Driver__r.Name,
            'dropoffAddress' => delivery.Dropoff_Address__c,
            'latitude' => delivery.Driver_Location__Latitude__s,
            'longitude' => delivery.Driver_Location__Longitude__s,
            'locationUpdatedAt' => delivery.Location_Updated_On__c,
            'tracking' => delivery.Status__c == 'In Transit',
            'navigationUrl' => navigationUrl
        };
    }

    private static Delivery_Notification__e buildNotice(Delivery__c delivery, Decimal latitude, Decimal longitude, String message) {
        return new Delivery_Notification__e(
            Delivery_Number__c = delivery.Name,
            Status__c = delivery.Status__c,
            Latitude__c = latitude,
            Longitude__c = longitude,
            Message__c = message,
            Navigation_Url__c = navigationUrl(delivery, latitude, longitude)
        );
    }

    private static String navigationUrl(Delivery__c delivery, Decimal latitude, Decimal longitude) {
        if (delivery.Status__c != 'In Transit' || latitude == null || longitude == null || String.isBlank(delivery.Dropoff_Address__c)) {
            return null;
        }
        return 'https://www.google.com/maps/dir/?api=1&origin='
            + String.valueOf(latitude) + ',' + String.valueOf(longitude)
            + '&destination=' + EncodingUtil.urlEncode(delivery.Dropoff_Address__c, 'UTF-8');
    }

    private static void publish(List<Delivery_Notification__e> notices) {
        if (!notices.isEmpty()) {
            EventBus.publish(notices);
        }
    }

    private static Map<String, String> error(String message) {
        return new Map<String, String>{ 'error' => message };
    }
}
