@IsTest
private class DeliveryTrackingTest {
    @IsTest
    static void locationAndStatusFollowTheRoute() {
        Delivery__c delivery = newDelivery('In Transit');
        insert delivery;
        delivery = [SELECT Name FROM Delivery__c WHERE Id = :delivery.Id];

        DeliveryTracking.Result located = DeliveryTracking.recordLocation(delivery.Name, 30.267200, -97.743100);
        System.assertEquals(200, located.statusCode);
        Map<String, Object> payload = (Map<String, Object>) located.body;
        System.assertEquals(true, payload.get('tracking'));
        System.assert(String.valueOf(payload.get('navigationUrl')).contains('Campus'));

        Delivery__c stored = [
            SELECT Driver_Location__Latitude__s, Driver_Location__Longitude__s, Location_Updated_On__c
            FROM Delivery__c
            WHERE Id = :delivery.Id
        ];
        System.assertEquals(30.267200, stored.Driver_Location__Latitude__s);
        System.assertEquals(-97.743100, stored.Driver_Location__Longitude__s);
        System.assertNotEquals(null, stored.Location_Updated_On__c);
        System.assertEquals(1, [SELECT COUNT() FROM Delivery_Location__c WHERE Delivery__c = :delivery.Id]);

        DeliveryTracking.Result attempted = DeliveryTracking.markStatus(delivery.Name, 'Attempted');
        System.assertEquals(200, attempted.statusCode);
        System.assertEquals('Attempted', ((Map<String, Object>) attempted.body).get('status'));
        System.assertNotEquals(null, [SELECT Attempted_On__c FROM Delivery__c WHERE Id = :delivery.Id].Attempted_On__c);

        DeliveryTracking.Result rejectedPing = DeliveryTracking.recordLocation(delivery.Name, 30.270000, -97.740000);
        System.assertEquals(409, rejectedPing.statusCode);

        DeliveryTracking.Result delivered = DeliveryTracking.markStatus(delivery.Name, 'Delivered');
        System.assertEquals(200, delivered.statusCode);
        Delivery__c finished = [SELECT Status__c, Delivered_On__c FROM Delivery__c WHERE Id = :delivery.Id];
        System.assertEquals('Delivered', finished.Status__c);
        System.assertNotEquals(null, finished.Delivered_On__c);
    }

    @IsTest
    static void pullListsOnlyInTransitAndRejectsBadMoves() {
        Delivery__c moving = newDelivery('In Transit');
        Delivery__c waiting = newDelivery('New');
        insert new List<Delivery__c>{ moving, waiting };
        moving = [SELECT Name FROM Delivery__c WHERE Id = :moving.Id];
        waiting = [SELECT Name FROM Delivery__c WHERE Id = :waiting.Id];

        DeliveryTracking.recordLocation(moving.Name, 30.250000, -97.750000);
        DeliveryTracking.Result listed = DeliveryTracking.pullInTransit();
        List<Object> rows = (List<Object>) listed.body;
        System.assertEquals(1, rows.size());

        System.assertEquals(404, DeliveryTracking.pullByNumber('DLV-9999').statusCode);
        System.assertEquals(400, DeliveryTracking.recordLocation(moving.Name, 120, 10).statusCode);
        System.assertEquals(409, DeliveryTracking.markStatus(waiting.Name, 'Delivered').statusCode);
        System.assertEquals(400, DeliveryTracking.markStatus(moving.Name, 'Cancelled').statusCode);
    }

    @IsTest
    static void restPullAndPush() {
        Delivery__c delivery = newDelivery('In Transit');
        insert delivery;
        delivery = [SELECT Name FROM Delivery__c WHERE Id = :delivery.Id];

        RestContext.request = new RestRequest();
        RestContext.response = new RestResponse();
        RestContext.request.requestURI = '/services/apexrest/delivery/v1/' + delivery.Name + '/location';
        RestContext.request.httpMethod = 'POST';
        RestContext.request.requestBody = Blob.valueOf('{"latitude":30.26,"longitude":-97.74}');
        DeliveryRest.push();
        System.assertEquals(200, RestContext.response.statusCode);

        RestContext.request = new RestRequest();
        RestContext.response = new RestResponse();
        RestContext.request.requestURI = '/services/apexrest/delivery/v1/' + delivery.Name;
        RestContext.request.httpMethod = 'GET';
        DeliveryRest.pull();
        System.assertEquals(200, RestContext.response.statusCode);
        System.assert(RestContext.response.responseBody.toString().contains(delivery.Name));

        RestContext.request = new RestRequest();
        RestContext.response = new RestResponse();
        RestContext.request.requestURI = '/services/apexrest/delivery/v1/in-transit';
        RestContext.request.httpMethod = 'GET';
        DeliveryRest.pull();
        System.assertEquals(200, RestContext.response.statusCode);
    }

    private static Delivery__c newDelivery(String status) {
        return new Delivery__c(
            Customer_Name__c = 'Route Test',
            Pickup_Address__c = '100 Warehouse Rd, Austin, TX',
            Dropoff_Address__c = '55 Campus Drive, Austin, TX',
            Scheduled_Date__c = Date.today(),
            Priority__c = 'Standard',
            Status__c = status
        );
    }
}
