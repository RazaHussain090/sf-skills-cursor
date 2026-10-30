public with sharing class OrderCatalog {
    public class CatalogItem {
        @AuraEnabled public Id productId;
        @AuraEnabled public String productName;
        @AuraEnabled public String unit;
        @AuraEnabled public Id warehouseId;
        @AuraEnabled public String warehouseName;
        @AuraEnabled public Decimal quantityOnHand;
    }

    public class LineInput {
        @AuraEnabled public Id productId { get; set; }
        @AuraEnabled public Decimal quantity { get; set; }
    }

    public class PlacedLine {
        @AuraEnabled public String productName;
        @AuraEnabled public String unit;
        @AuraEnabled public Decimal quantity;
    }

    public class PlacedOrder {
        @AuraEnabled public String deliveryNumber;
        @AuraEnabled public String warehouseName;
        @AuraEnabled public String dropoffAddress;
        @AuraEnabled public Date scheduledDate;
        @AuraEnabled public List<PlacedLine> lines;
    }

    public class DeliveryLookup {
        @AuraEnabled public String deliveryNumber;
        @AuraEnabled public String status;
        @AuraEnabled public String fulfillment;
        @AuraEnabled public Date scheduledDate;
        @AuraEnabled public String dropoffAddress;
        @AuraEnabled public Boolean tracking;
        @AuraEnabled public Decimal latitude;
        @AuraEnabled public Decimal longitude;
        @AuraEnabled public Datetime locationUpdatedAt;
    }

    @AuraEnabled(cacheable=true)
    public static List<CatalogItem> listCatalog() {
        Map<Id, CatalogItem> bestByProduct = new Map<Id, CatalogItem>();
        for (Stock__c stock : [
            SELECT Product__c, Product__r.Name, Product__r.Unit__c,
                Warehouse__c, Warehouse__r.Name, Quantity_On_Hand__c
            FROM Stock__c
            WHERE Quantity_On_Hand__c > 0
            AND Warehouse__r.Status__c = 'Open'
            ORDER BY Quantity_On_Hand__c DESC, Warehouse__r.Name
        ]) {
            CatalogItem current = bestByProduct.get(stock.Product__c);
            if (current == null || stock.Quantity_On_Hand__c > current.quantityOnHand) {
                bestByProduct.put(stock.Product__c, toItem(stock));
            }
        }
        List<CatalogItem> items = bestByProduct.values();
        items.sort(new CatalogNameSort());
        return items;
    }

    @AuraEnabled
    public static PlacedOrder placeOrder(
        String customerName,
        String phone,
        String dropoffAddress,
        Date scheduledDate,
        List<LineInput> lines
    ) {
        String name = customerName == null ? null : customerName.trim();
        String dropoff = dropoffAddress == null ? null : dropoffAddress.trim();
        if (String.isBlank(name)) {
            fail('Enter the customer name.');
        }
        if (String.isBlank(dropoff)) {
            fail('Enter the dropoff address.');
        }
        if (scheduledDate == null) {
            fail('Enter the date.');
        }
        if (scheduledDate < Date.today()) {
            fail('Choose today or a later date.');
        }

        Map<Id, Decimal> quantities = combine(lines);
        if (quantities.isEmpty()) {
            fail('Add a product before placing the order.');
        }

        Map<Id, CatalogItem> catalog = new Map<Id, CatalogItem>();
        for (CatalogItem item : listCatalog()) {
            catalog.put(item.productId, item);
        }

        Id warehouseId;
        String warehouseName;
        List<Delivery_Line__c> deliveryLines = new List<Delivery_Line__c>();
        List<PlacedLine> placedLines = new List<PlacedLine>();
        for (Id productId : quantities.keySet()) {
            CatalogItem item = catalog.get(productId);
            Decimal quantity = quantities.get(productId);
            if (item == null) {
                fail('A product in the cart is no longer on hand.');
            }
            if (quantity <= 0 || quantity != quantity.intValue()) {
                fail('Enter a whole quantity greater than zero.');
            }
            if (quantity > item.quantityOnHand) {
                fail(item.productName + ' only has ' + item.quantityOnHand.intValue() + ' on hand.');
            }
            if (warehouseId == null) {
                warehouseId = item.warehouseId;
                warehouseName = item.warehouseName;
            } else if (warehouseId != item.warehouseId) {
                fail(item.productName + ' ships from ' + item.warehouseName + '. Place a separate order.');
            }
            deliveryLines.add(new Delivery_Line__c(
                Product__c = productId,
                Quantity__c = quantity,
                Status__c = 'To Pick'
            ));
            PlacedLine placed = new PlacedLine();
            placed.productName = item.productName;
            placed.unit = item.unit;
            placed.quantity = quantity;
            placedLines.add(placed);
        }

        Warehouse__c warehouse = [
            SELECT Address__c, Status__c
            FROM Warehouse__c
            WHERE Id = :warehouseId
            LIMIT 1
        ];
        if (warehouse.Status__c != 'Open') {
            fail('That warehouse is closed.');
        }

        Delivery__c delivery = new Delivery__c(
            Customer_Name__c = name,
            Contact_Phone__c = String.isBlank(phone) ? null : phone.trim(),
            Dropoff_Address__c = dropoff,
            Pickup_Address__c = warehouse.Address__c,
            Scheduled_Date__c = scheduledDate,
            Warehouse__c = warehouseId,
            Status__c = 'New',
            Priority__c = 'Standard',
            Fulfillment__c = 'To Pick'
        );
        insert delivery;
        for (Delivery_Line__c line : deliveryLines) {
            line.Delivery__c = delivery.Id;
        }
        insert deliveryLines;

        delivery = [SELECT Name FROM Delivery__c WHERE Id = :delivery.Id];
        PlacedOrder placed = new PlacedOrder();
        placed.deliveryNumber = delivery.Name;
        placed.warehouseName = warehouseName;
        placed.dropoffAddress = dropoff;
        placed.scheduledDate = scheduledDate;
        placed.lines = placedLines;
        return placed;
    }

    @AuraEnabled
    public static DeliveryLookup lookupDelivery(String deliveryNumber) {
        String normalized = normalize(deliveryNumber);
        if (String.isBlank(normalized)) {
            fail('Enter a delivery number.');
        }
        List<Delivery__c> rows = [
            SELECT Name, Status__c, Fulfillment__c, Scheduled_Date__c, Dropoff_Address__c,
                Driver_Location__Latitude__s, Driver_Location__Longitude__s, Location_Updated_On__c
            FROM Delivery__c
            WHERE Name = :normalized
            LIMIT 1
        ];
        if (rows.isEmpty()) {
            fail('No delivery found for ' + normalized + '.');
        }
        Delivery__c delivery = rows[0];
        DeliveryLookup result = new DeliveryLookup();
        result.deliveryNumber = delivery.Name;
        result.status = delivery.Status__c;
        result.fulfillment = delivery.Fulfillment__c;
        result.scheduledDate = delivery.Scheduled_Date__c;
        result.dropoffAddress = delivery.Dropoff_Address__c;
        result.tracking = delivery.Status__c == 'In Transit';
        if (result.tracking == true) {
            result.latitude = delivery.Driver_Location__Latitude__s;
            result.longitude = delivery.Driver_Location__Longitude__s;
            result.locationUpdatedAt = delivery.Location_Updated_On__c;
        }
        return result;
    }

    private static CatalogItem toItem(Stock__c stock) {
        CatalogItem item = new CatalogItem();
        item.productId = stock.Product__c;
        item.productName = stock.Product__r.Name;
        item.unit = stock.Product__r.Unit__c;
        item.warehouseId = stock.Warehouse__c;
        item.warehouseName = stock.Warehouse__r.Name;
        item.quantityOnHand = stock.Quantity_On_Hand__c;
        return item;
    }

    private static Map<Id, Decimal> combine(List<LineInput> lines) {
        Map<Id, Decimal> quantities = new Map<Id, Decimal>();
        if (lines == null) {
            return quantities;
        }
        for (LineInput line : lines) {
            if (line == null || line.productId == null || line.quantity == null) {
                continue;
            }
            Decimal current = quantities.containsKey(line.productId) ? quantities.get(line.productId) : 0;
            quantities.put(line.productId, current + line.quantity);
        }
        return quantities;
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

    private static void fail(String message) {
        AuraHandledException error = new AuraHandledException(message);
        error.setMessage(message);
        throw error;
    }

    private class CatalogNameSort implements Comparator<CatalogItem> {
        public Integer compare(CatalogItem left, CatalogItem right) {
            String leftName = left.productName == null ? '' : left.productName.toLowerCase();
            String rightName = right.productName == null ? '' : right.productName.toLowerCase();
            return leftName.compareTo(rightName);
        }
    }
}
