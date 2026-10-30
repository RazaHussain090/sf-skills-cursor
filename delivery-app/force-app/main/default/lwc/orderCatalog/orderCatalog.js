import { LightningElement, wire } from 'lwc';
import { refreshApex } from '@salesforce/apex';
import listCatalog from '@salesforce/apex/OrderCatalog.listCatalog';
import placeOrder from '@salesforce/apex/OrderCatalog.placeOrder';
import lookupDelivery from '@salesforce/apex/OrderCatalog.lookupDelivery';

export default class OrderCatalog extends LightningElement {
    wiredCatalog;
    catalog = [];
    quantities = {};
    cart = [];
    customerName = '';
    phone = '';
    dropoffAddress = '';
    scheduledDate;
    message;
    errorMessage;
    isPlacing = false;
    placedOrder;
    lookupNumber = '';
    lookupResult;
    lookupError;
    isLooking = false;

    connectedCallback() {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const month = String(tomorrow.getMonth() + 1).padStart(2, '0');
        const day = String(tomorrow.getDate()).padStart(2, '0');
        this.scheduledDate = `${tomorrow.getFullYear()}-${month}-${day}`;
    }

    @wire(listCatalog)
    wiredList(result) {
        this.wiredCatalog = result;
        if (result.data) {
            this.catalog = result.data;
        } else if (result.error) {
            this.errorMessage = this.readError(result.error);
        }
    }

    get catalogRows() {
        const warehouseId = this.cartWarehouseId;
        return this.catalog.map((item) => {
            const blocked = Boolean(warehouseId && item.warehouseId !== warehouseId);
            return {
                ...item,
                quantity: this.quantities[item.productId] || 1,
                blocked,
                rowNote: blocked
                    ? `Ships from ${item.warehouseName}. Place a separate order.`
                    : `${item.quantityOnHand} on hand at ${item.warehouseName}`
            };
        });
    }

    get hasCatalog() {
        return this.catalogRows.length > 0;
    }

    get cartWarehouseId() {
        return this.cart.length ? this.cart[0].warehouseId : null;
    }

    get cartWarehouseName() {
        return this.cart.length ? this.cart[0].warehouseName : null;
    }

    get hasCart() {
        return this.cart.length > 0;
    }

    get placeLabel() {
        return this.isPlacing ? 'Placing order...' : 'Place order';
    }

    get lookupLabel() {
        return this.isLooking ? 'Looking up...' : 'Look up';
    }

    get locationText() {
        if (!this.lookupResult || !this.lookupResult.tracking || this.lookupResult.latitude == null) {
            return null;
        }
        return `${this.lookupResult.latitude}, ${this.lookupResult.longitude}`;
    }

    handleQuantity(event) {
        const productId = event.target.dataset.id;
        this.quantities = { ...this.quantities, [productId]: Number(event.target.value) };
    }

    handleField(event) {
        this[event.target.name] = event.target.value;
    }

    addToCart(event) {
        const productId = event.currentTarget.dataset.id;
        const item = this.catalog.find((row) => row.productId === productId);
        const quantity = Number(this.quantities[productId] || 1);
        if (!item) {
            return;
        }
        if (!Number.isInteger(quantity) || quantity < 1) {
            this.errorMessage = 'Enter a whole quantity greater than zero.';
            return;
        }
        if (quantity > item.quantityOnHand) {
            this.errorMessage = `${item.productName} only has ${item.quantityOnHand} on hand.`;
            return;
        }
        if (this.cartWarehouseId && this.cartWarehouseId !== item.warehouseId) {
            this.errorMessage = `${item.productName} ships from ${item.warehouseName}. Place a separate order.`;
            return;
        }
        const existing = this.cart.find((row) => row.productId === productId);
        const nextQuantity = existing ? existing.quantity + quantity : quantity;
        if (nextQuantity > item.quantityOnHand) {
            this.errorMessage = `${item.productName} only has ${item.quantityOnHand} on hand.`;
            return;
        }
        this.errorMessage = undefined;
        this.message = undefined;
        if (existing) {
            this.cart = this.cart.map((row) => (row.productId === productId ? { ...row, quantity: nextQuantity } : row));
        } else {
            this.cart = [...this.cart, { ...item, quantity }];
        }
    }

    removeFromCart(event) {
        const productId = event.currentTarget.dataset.id;
        this.cart = this.cart.filter((row) => row.productId !== productId);
    }

    async place() {
        this.errorMessage = undefined;
        this.message = undefined;
        if (!this.hasCart) {
            this.errorMessage = 'Add a product before placing the order.';
            return;
        }
        this.isPlacing = true;
        try {
            this.placedOrder = await placeOrder({
                customerName: this.customerName,
                phone: this.phone,
                dropoffAddress: this.dropoffAddress,
                scheduledDate: this.scheduledDate,
                lines: this.cart.map((row) => ({ productId: row.productId, quantity: row.quantity }))
            });
            this.cart = [];
            this.customerName = '';
            this.phone = '';
            this.dropoffAddress = '';
            this.message = `Order ${this.placedOrder.deliveryNumber} is with the warehouse to pick.`;
            await refreshApex(this.wiredCatalog);
        } catch (error) {
            this.errorMessage = this.readError(error);
        } finally {
            this.isPlacing = false;
        }
    }

    async lookup() {
        this.lookupError = undefined;
        this.lookupResult = undefined;
        this.isLooking = true;
        try {
            this.lookupResult = await lookupDelivery({ deliveryNumber: this.lookupNumber });
        } catch (error) {
            this.lookupError = this.readError(error);
        } finally {
            this.isLooking = false;
        }
    }

    readError(error) {
        if (Array.isArray(error?.body)) {
            return error.body.map((row) => row.message).join(' ');
        }
        return error?.body?.message || error?.message || 'Something went wrong.';
    }
}
