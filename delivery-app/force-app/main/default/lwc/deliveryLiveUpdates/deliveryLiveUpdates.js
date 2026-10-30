import { LightningElement, api, wire } from 'lwc';
import { subscribe, unsubscribe, onError, isEmpEnabled } from 'lightning/empApi';
import { getRecord, getFieldValue, notifyRecordUpdateAvailable } from 'lightning/uiRecordApi';
import DELIVERY_NAME from '@salesforce/schema/Delivery__c.Name';

const CHANNEL = '/event/Delivery_Notification__e';
const MAX_EVENTS = 25;

export default class DeliveryLiveUpdates extends LightningElement {
    @api recordId;

    deliveryNumber;
    events = [];
    connected = false;
    unavailable = false;
    errorMessage;
    subscription;

    @wire(getRecord, { recordId: '$recordId', fields: [DELIVERY_NAME] })
    wiredDelivery({ data }) {
        if (data) {
            this.deliveryNumber = getFieldValue(data, DELIVERY_NAME);
        }
    }

    get visibleEvents() {
        if (!this.recordId) {
            return this.events;
        }
        if (!this.deliveryNumber) {
            return [];
        }
        return this.events.filter((item) => item.deliveryNumber === this.deliveryNumber);
    }

    get hasEvents() {
        return this.visibleEvents.length > 0;
    }

    get showEmpty() {
        return this.connected && !this.hasEvents;
    }

    get statusText() {
        if (this.unavailable) {
            return 'Live updates are not available on this page.';
        }
        if (!this.connected) {
            return 'Connecting';
        }
        if (this.deliveryNumber) {
            return `Listening for ${this.deliveryNumber}`;
        }
        return 'Listening for every delivery';
    }

    get emptyText() {
        return this.recordId
            ? 'Waiting for an update on this delivery.'
            : 'Waiting for a status change or a location ping.';
    }

    connectedCallback() {
        this.registerErrorListener();
        const enabled = isEmpEnabled();
        if (enabled && typeof enabled.then === 'function') {
            enabled.then((value) => this.startOrExplain(value));
            return;
        }
        this.startOrExplain(enabled);
    }

    disconnectedCallback() {
        if (this.subscription) {
            unsubscribe(this.subscription, () => {});
            this.subscription = undefined;
        }
    }

    startOrExplain(enabled) {
        if (enabled) {
            this.handleSubscribe();
            return;
        }
        this.unavailable = true;
    }

    handleSubscribe() {
        subscribe(CHANNEL, -1, (message) => this.addEvent(message)).then((response) => {
            this.subscription = response;
            this.connected = true;
        });
    }

    registerErrorListener() {
        onError(() => {
            this.connected = false;
            this.errorMessage = 'The live update channel could not be opened.';
        });
    }

    addEvent(message) {
        const payload = message && message.data && message.data.payload;
        if (!payload) {
            return;
        }
        const replayId = message.data.event && message.data.event.replayId;
        const item = {
            key: `${replayId}-${payload.CreatedDate || ''}`,
            deliveryNumber: payload.Delivery_Number__c,
            status: payload.Status__c,
            message: payload.Message__c,
            createdDate: payload.CreatedDate,
            coordinates: this.coordinates(payload.Latitude__c, payload.Longitude__c),
            navigationUrl: payload.Navigation_Url__c
        };
        this.events = [item, ...this.events].slice(0, MAX_EVENTS);
        if (this.recordId && this.deliveryNumber && item.deliveryNumber === this.deliveryNumber) {
            notifyRecordUpdateAvailable([{ recordId: this.recordId }]).catch(() => {});
        }
    }

    coordinates(latitude, longitude) {
        if (latitude === null || latitude === undefined || longitude === null || longitude === undefined) {
            return undefined;
        }
        return `${Number(latitude).toFixed(5)}, ${Number(longitude).toFixed(5)}`;
    }
}
