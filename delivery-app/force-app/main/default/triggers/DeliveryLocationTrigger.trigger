trigger DeliveryLocationTrigger on Delivery_Location__c (after insert) {
    DeliveryTracking.publishLocationPings(Trigger.new);
}
