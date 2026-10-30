trigger DeliveryTrigger on Delivery__c (after update) {
    List<Delivery__c> changed = new List<Delivery__c>();
    for (Delivery__c delivery : Trigger.new) {
        if (Trigger.oldMap.get(delivery.Id).Status__c != delivery.Status__c) {
            changed.add(delivery);
        }
    }
    if (!changed.isEmpty()) {
        DeliveryTracking.publishStatusChanges(changed);
    }
}
