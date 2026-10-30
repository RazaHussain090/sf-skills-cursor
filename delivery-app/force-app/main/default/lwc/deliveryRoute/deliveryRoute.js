import { LightningElement, api, wire } from 'lwc';
import { getRecord, getFieldValue, updateRecord, notifyRecordUpdateAvailable } from 'lightning/uiRecordApi';
import { refreshApex } from '@salesforce/apex';

const FIELDS = [
    'Delivery__c.Status__c',
    'Delivery__c.Driver__c',
    'Delivery__c.Driver__r.Name',
    'Delivery__c.Dropoff_Address__c',
    'Delivery__c.Pickup_Address__c',
    'Delivery__c.Attempted_On__c',
    'Delivery__c.Delivered_On__c',
    'Delivery__c.Location_Updated_On__c',
    'Delivery__c.Driver_Location__Latitude__s',
    'Delivery__c.Driver_Location__Longitude__s'
];

const WRITE_INTERVAL_MS = 15000;
const POLL_INTERVAL_MS = 15000;

export default class DeliveryRoute extends LightningElement {
    @api recordId;

    wiredResult;
    record;
    errorMessage;
    isBusy = false;
    sharing = false;
    watchId;
    pollId;
    lastWrite = 0;
    writing = false;

    @wire(getRecord, { recordId: '$recordId', fields: FIELDS })
    wiredDelivery(result) {
        this.wiredResult = result;
        if (result.data) {
            this.record = result.data;
            this.syncPoll();
        } else if (result.error) {
            this.errorMessage = 'Could not load this delivery.';
        }
    }

    disconnectedCallback() {
        this.stopWatch();
        this.clearPoll();
    }

    get isLoading() {
        return !this.record && !this.errorMessage;
    }

    get status() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Status__c') : undefined;
    }

    get driverId() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Driver__c') : undefined;
    }

    get driverName() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Driver__r.Name') : undefined;
    }

    get dropoff() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Dropoff_Address__c') : undefined;
    }

    get pickup() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Pickup_Address__c') : undefined;
    }

    get attemptedOn() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Attempted_On__c') : undefined;
    }

    get deliveredOn() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Delivered_On__c') : undefined;
    }

    get locationUpdatedOn() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Location_Updated_On__c') : undefined;
    }

    get latitudeValue() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Driver_Location__Latitude__s') : null;
    }

    get longitudeValue() {
        return this.record ? getFieldValue(this.record, 'Delivery__c.Driver_Location__Longitude__s') : null;
    }

    get showStart() {
        return this.status === 'New' || this.status === 'Assigned';
    }

    get onRoute() {
        return this.status === 'In Transit' || this.status === 'Attempted';
    }

    get canAttempt() {
        return this.status === 'In Transit';
    }

    get canResume() {
        return this.status === 'Attempted';
    }

    get isDelivered() {
        return this.status === 'Delivered';
    }

    get isOther() {
        return this.record && !this.showStart && !this.onRoute && !this.isDelivered;
    }

    get hasLocation() {
        return this.latitudeValue !== null && this.latitudeValue !== undefined
            && this.longitudeValue !== null && this.longitudeValue !== undefined;
    }

    get waitingForLocation() {
        return this.onRoute && !this.hasLocation;
    }

    get needsDriver() {
        return this.onRoute && !this.driverId;
    }

    get shareLabel() {
        return this.sharing ? 'Stop sharing' : 'Share location';
    }

    get latitudeText() {
        return this.hasLocation ? Number(this.latitudeValue).toFixed(5) : '';
    }

    get longitudeText() {
        return this.hasLocation ? Number(this.longitudeValue).toFixed(5) : '';
    }

    get mapUrl() {
        if (!this.hasLocation) {
            return undefined;
        }
        const lat = Number(this.latitudeValue);
        const lng = Number(this.longitudeValue);
        const pad = 0.01;
        const bbox = [lng - pad, lat - pad, lng + pad, lat + pad].join('%2C');
        return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat}%2C${lng}`;
    }

    get pinUrl() {
        if (!this.hasLocation) {
            return undefined;
        }
        return `https://www.google.com/maps/search/?api=1&query=${this.latitudeValue},${this.longitudeValue}`;
    }

    async startRoute() {
        await this.saveStatus('In Transit', 'On Route');
    }

    async resumeRoute() {
        await this.saveStatus('In Transit', 'On Route');
    }

    async attemptDelivery() {
        await this.saveStatus('Attempted', 'On Route', { Attempted_On__c: new Date().toISOString() });
    }

    async markDelivered() {
        this.stopWatch();
        await this.saveStatus('Delivered', 'Available', { Delivered_On__c: new Date().toISOString() });
    }

    toggleShare() {
        if (this.sharing) {
            this.stopWatch();
            return;
        }
        this.startWatch();
    }

    navigateDropoff() {
        this.openMaps(this.dropoff);
    }

    navigatePickup() {
        this.openMaps(this.pickup);
    }

    async saveStatus(deliveryStatus, driverStatus, extraFields) {
        this.errorMessage = undefined;
        if (!this.driverId) {
            this.errorMessage = 'Assign a driver before updating the route.';
            return;
        }
        this.isBusy = true;
        try {
            const fields = Object.assign({ Id: this.recordId, Status__c: deliveryStatus }, extraFields);
            await updateRecord({ fields });
            await updateRecord({
                fields: {
                    Id: this.driverId,
                    Status__c: driverStatus
                }
            });
            await this.refreshRecords();
        } catch (error) {
            this.errorMessage = this.messageFrom(error);
        } finally {
            this.isBusy = false;
        }
    }

    startWatch() {
        this.errorMessage = undefined;
        if (!this.driverId) {
            this.errorMessage = 'Assign a driver before sharing a location.';
            return;
        }
        if (!navigator.geolocation) {
            this.errorMessage = 'This phone cannot share its location with Salesforce.';
            return;
        }
        this.sharing = true;
        this.lastWrite = 0;
        this.watchId = navigator.geolocation.watchPosition(
            (position) => this.onPosition(position),
            (error) => this.onGeoError(error),
            { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 }
        );
    }

    stopWatch() {
        if (this.watchId !== undefined && navigator.geolocation) {
            navigator.geolocation.clearWatch(this.watchId);
        }
        this.watchId = undefined;
        this.sharing = false;
    }

    onPosition(position) {
        if (!this.sharing) {
            return;
        }
        const now = Date.now();
        if (this.lastWrite && now - this.lastWrite < WRITE_INTERVAL_MS) {
            return;
        }
        this.writeLocation(position.coords.latitude, position.coords.longitude);
    }

    onGeoError(error) {
        this.stopWatch();
        if (error && error.code === 1) {
            this.errorMessage = 'Location permission was denied. Allow location for Salesforce, then tap Share location again.';
            return;
        }
        this.errorMessage = 'The phone could not read a GPS position.';
    }

    async writeLocation(latitude, longitude) {
        if (!this.sharing || this.writing || !this.driverId) {
            return;
        }
        this.writing = true;
        const updatedOn = new Date().toISOString();
        try {
            await updateRecord({
                fields: {
                    Id: this.recordId,
                    Driver_Location__Latitude__s: latitude,
                    Driver_Location__Longitude__s: longitude,
                    Location_Updated_On__c: updatedOn
                }
            });
            await updateRecord({
                fields: {
                    Id: this.driverId,
                    Current_Location__Latitude__s: latitude,
                    Current_Location__Longitude__s: longitude,
                    Location_Updated_On__c: updatedOn
                }
            });
            this.lastWrite = Date.now();
            await this.refreshRecords();
        } catch (error) {
            this.errorMessage = this.messageFrom(error);
        } finally {
            this.writing = false;
        }
    }

    async refreshRecords() {
        const updates = [{ recordId: this.recordId }];
        if (this.driverId) {
            updates.push({ recordId: this.driverId });
        }
        try {
            await notifyRecordUpdateAvailable(updates);
        } catch (ignored) {
            // The record save already finished. Polling reloads the pin.
        }
        if (this.wiredResult) {
            await refreshApex(this.wiredResult);
        }
    }

    syncPoll() {
        if (this.onRoute && !this.pollId) {
            this.pollId = window.setInterval(() => {
                if (this.wiredResult) {
                    refreshApex(this.wiredResult);
                }
            }, POLL_INTERVAL_MS);
        }
        if (!this.onRoute) {
            this.clearPoll();
        }
    }

    clearPoll() {
        if (this.pollId) {
            window.clearInterval(this.pollId);
            this.pollId = undefined;
        }
    }

    openMaps(address) {
        if (!address) {
            this.errorMessage = 'This delivery has no address to navigate to.';
            return;
        }
        const url = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(address)}&travelmode=driving`;
        window.open(url, '_blank', 'noopener');
    }

    messageFrom(error) {
        const body = error && error.body;
        if (Array.isArray(body)) {
            return body.map((item) => item.message).filter(Boolean).join(' ');
        }
        if (body && typeof body.message === 'string') {
            return body.message;
        }
        return 'Could not update the delivery.';
    }
}