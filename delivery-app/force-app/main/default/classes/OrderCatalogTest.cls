@IsTest
private class OrderCatalogTest {
    @IsTest
    static void catalogKeepsTheWarehouseWithTheMostOnHand() {
        Warehouse__c main = warehouse('Austin Main', 'Open');
        Warehouse__c supply = warehouse('Supply Court', 'Open');
        Warehouse__c closed = warehouse('Closed Dock', 'Closed');
        insert new List<Warehouse__c>{ main, supply, closed };

        Product__c gloves = product('Exam Gloves', 'TEST-GL-200', 'Box');
        Product__c towels = product('Paper Towels', 'TEST-PT-100', 'Case');
        Product__c empty = product('Empty Shelf', 'TEST-EM-000', 'Each');
        insert new List<Product__c>{ gloves, towels, empty };

        insert new List<Stock__c>{
            stock(main, gloves, 24, 'B-02'),
            stock(supply, gloves, 4, 'S-02'),
            stock(main, towels, 40, 'A-12'),
            stock(closed, towels, 100, 'Z-01'),
            stock(main, empty, 0, 'Z-02')
        };

        List<OrderCatalog.CatalogItem> items = OrderCatalog.listCatalog();
        System.assertEquals(2, items.size());
        System.assertEquals('Exam Gloves', items[0].productName);
        System.assertEquals(main.Id, items[0].warehouseId);
        System.assertEquals(24, items[0].quantityOnHand);
        System.assertEquals('Paper Towels', items[1].productName);
        System.assertEquals(40, items[1].quantityOnHand);
    }

    @IsTest
    static void placeOrderCreatesLinesAndLeavesStockAlone() {
        Warehouse__c main = warehouse('Austin Main', 'Open');
        insert main;
        Product__c towels = product('Paper Towels', 'TEST-PT-101', 'Case');
        Product__c coffee = product('Coffee Beans', 'TEST-CF-700', 'Case');
        insert new List<Product__c>{ towels, coffee };
        insert new List<Stock__c>{
            stock(main, towels, 40, 'A-12'),
            stock(main, coffee, 12, 'D-01')
        };

        Test.startTest();
        OrderCatalog.PlacedOrder placed = OrderCatalog.placeOrder(
            ' Northwind Market ',
            '555-2001',
            ' 14 Oak Street, Austin, TX ',
            Date.today().addDays(1),
            new List<OrderCatalog.LineInput>{
                line(towels.Id, 2),
                line(coffee.Id, 1)
            }
        );
        Test.stopTest();

        System.assert(placed.deliveryNumber.startsWith('DLV-'));
        System.assertEquals('Austin Main', placed.warehouseName);
        System.assertEquals(2, placed.lines.size());

        Delivery__c delivery = [
            SELECT Status__c, Priority__c, Fulfillment__c, Warehouse__c, Pickup_Address__c,
                Customer_Name__c, Contact_Phone__c, Dropoff_Address__c
            FROM Delivery__c
            WHERE Name = :placed.deliveryNumber
        ];
        System.assertEquals('New', delivery.Status__c);
        System.assertEquals('Standard', delivery.Priority__c);
        System.assertEquals('To Pick', delivery.Fulfillment__c);
        System.assertEquals(main.Id, delivery.Warehouse__c);
        System.assertEquals('100 Warehouse Rd, Austin, TX', delivery.Pickup_Address__c);
        System.assertEquals('Northwind Market', delivery.Customer_Name__c);
        System.assertEquals('555-2001', delivery.Contact_Phone__c);
        System.assertEquals('14 Oak Street, Austin, TX', delivery.Dropoff_Address__c);
        System.assertEquals(2, [SELECT COUNT() FROM Delivery_Line__c WHERE Delivery__c = :delivery.Id AND Status__c = 'To Pick']);
        System.assertEquals(40, [SELECT Quantity_On_Hand__c FROM Stock__c WHERE Product__c = :towels.Id].Quantity_On_Hand__c);
        System.assertEquals(12, [SELECT Quantity_On_Hand__c FROM Stock__c WHERE Product__c = :coffee.Id].Quantity_On_Hand__c);
    }

    @IsTest
    static void placeOrderRejectsASecondWarehouseAndAShortShelf() {
        Warehouse__c main = warehouse('Austin Main', 'Open');
        Warehouse__c supply = warehouse('Supply Court', 'Open');
        insert new List<Warehouse__c>{ main, supply };
        Product__c towels = product('Paper Towels', 'TEST-PT-102', 'Case');
        Product__c bibs = product('Dental Bibs', 'TEST-DN-600', 'Box');
        insert new List<Product__c>{ towels, bibs };
        insert new List<Stock__c>{
            stock(main, towels, 40, 'A-12'),
            stock(supply, bibs, 20, 'S-01')
        };

        try {
            OrderCatalog.placeOrder('Cedar School', null, '55 Campus Drive', Date.today(), new List<OrderCatalog.LineInput>{
                line(towels.Id, 1),
                line(bibs.Id, 1)
            });
            System.assert(false, 'Expected a second warehouse to be refused.');
        } catch (AuraHandledException error) {
            System.assert(error.getMessage().contains('separate order'));
        }

        try {
            OrderCatalog.placeOrder('Cedar School', null, '55 Campus Drive', Date.today(), new List<OrderCatalog.LineInput>{
                line(towels.Id, 41)
            });
            System.assert(false, 'Expected a short shelf to be refused.');
        } catch (AuraHandledException error) {
            System.assert(error.getMessage().contains('on hand'));
        }

        System.assertEquals(0, [SELECT COUNT() FROM Delivery__c]);
    }

    @IsTest
    static void placeOrderRequiresNameDropoffAndAProduct() {
        assertFailure(null, '14 Oak Street', Date.today(), new List<OrderCatalog.LineInput>(), 'customer name');
        assertFailure('Northwind', null, Date.today(), new List<OrderCatalog.LineInput>(), 'dropoff');
        assertFailure('Northwind', '14 Oak Street', Date.today().addDays(-1), new List<OrderCatalog.LineInput>(), 'later date');
        assertFailure('Northwind', '14 Oak Street', Date.today(), new List<OrderCatalog.LineInput>(), 'Add a product');
    }

    @IsTest
    static void lookupReturnsStatusAndLocationWithoutADriver() {
        Warehouse__c main = warehouse('Austin Main', 'Open');
        insert main;
        Driver__c driver = new Driver__c(Name = 'Jordan Lee', Status__c = 'On Route');
        insert driver;
        Delivery__c moving = new Delivery__c(
            Customer_Name__c = 'Cedar School',
            Pickup_Address__c = main.Address__c,
            Dropoff_Address__c = '55 Campus Drive, Austin, TX',
            Scheduled_Date__c = Date.today(),
            Priority__c = 'Standard',
            Status__c = 'In Transit',
            Fulfillment__c = 'Ready',
            Warehouse__c = main.Id,
            Driver__c = driver.Id,
            Notes__c = 'Internal note',
            Driver_Location__Latitude__s = 30.2672,
            Driver_Location__Longitude__s = -97.7431,
            Location_Updated_On__c = System.now()
        );
        insert moving;
        moving = [SELECT Name FROM Delivery__c WHERE Id = :moving.Id];

        OrderCatalog.DeliveryLookup found = OrderCatalog.lookupDelivery(' ' + moving.Name.toLowerCase() + ' ');
        System.assertEquals(moving.Name, found.deliveryNumber);
        System.assertEquals('In Transit', found.status);
        System.assertEquals('Ready', found.fulfillment);
        System.assertEquals(true, found.tracking);
        System.assertEquals(30.2672, found.latitude);
        System.assertEquals(-97.7431, found.longitude);
        System.assertNotEquals(null, found.locationUpdatedAt);

        try {
            OrderCatalog.lookupDelivery('DLV-9999');
            System.assert(false, 'Expected a missing delivery to be refused.');
        } catch (AuraHandledException error) {
            System.assert(error.getMessage().contains('No delivery found'));
        }
    }

    private static void assertFailure(String name, String dropoff, Date scheduledDate, List<OrderCatalog.LineInput> lines, String expected) {
        try {
            OrderCatalog.placeOrder(name, null, dropoff, scheduledDate, lines);
            System.assert(false, 'Expected failure containing ' + expected);
        } catch (AuraHandledException error) {
            System.assert(error.getMessage().contains(expected), error.getMessage());
        }
    }

    private static Warehouse__c warehouse(String name, String status) {
        return new Warehouse__c(
            Name = name,
            Address__c = '100 Warehouse Rd, Austin, TX',
            Status__c = status
        );
    }

    private static Product__c product(String name, String sku, String unit) {
        return new Product__c(Name = name, SKU__c = sku, Unit__c = unit);
    }

    private static Stock__c stock(Warehouse__c warehouse, Product__c product, Decimal quantity, String bin) {
        return new Stock__c(
            Warehouse__c = warehouse.Id,
            Product__c = product.Id,
            Quantity_On_Hand__c = quantity,
            Bin__c = bin
        );
    }

    private static OrderCatalog.LineInput line(Id productId, Decimal quantity) {
        OrderCatalog.LineInput input = new OrderCatalog.LineInput();
        input.productId = productId;
        input.quantity = quantity;
        return input;
    }
}
