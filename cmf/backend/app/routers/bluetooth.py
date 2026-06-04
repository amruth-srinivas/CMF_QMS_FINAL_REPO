"""
Bluetooth device management module using bleak library.
Handles scanning, connecting, and disconnecting Bluetooth devices.
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date, datetime
import asyncio
from bleak import BleakScanner, BleakClient
import logging
from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import BluetoothDevice
from app.models.instrument_setup import LibraryInstrument

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bluetooth", tags=["bluetooth"])


def _normalize_mac(mac: str) -> str:
    return mac.replace("-", ":").strip().upper()


def _next_calibration_date_to_str(value: Any) -> Optional[str]:
    """ORM/DB may return date objects; API contract is YYYY-MM-DD string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# Store connected devices
connected_devices: Dict[str, BleakClient] = {}


async def _read_notification_sample(
    client: BleakClient,
    characteristic_uuid: str,
    timeout: float = 2.0,
) -> Optional[str]:
    """
    Subscribe to notifications on a characteristic and return a single sample.
    This matches the existing notification_handler/monitor_data pattern but
    runs for a short time and returns the first decoded value.
    """
    last_value: Dict[str, Optional[str]] = {"value": None}
    got_value = asyncio.Event()

    def _handler(sender: int, data: bytearray) -> None:
        try:
            decoded = data.decode("utf-8").strip()
        except Exception:
            decoded = data.hex()
        last_value["value"] = decoded
        if not got_value.is_set():
            got_value.set()

    try:
        await client.start_notify(characteristic_uuid, _handler)
        try:
            await asyncio.wait_for(got_value.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # No value within timeout; return whatever we have (likely None)
            pass
    finally:
        try:
            await client.stop_notify(characteristic_uuid)
        except Exception:
            # Ignore stop errors; connection is still considered successful
            pass

    return last_value["value"]

class DeviceInfo(BaseModel):
    """Bluetooth device information"""
    address: str
    name: Optional[str] = None
    rssi: Optional[int] = None
    connected: bool = False

class ConnectRequest(BaseModel):
    """Request to connect to a Bluetooth device"""
    address: str
    name: Optional[str] = None

class DisconnectRequest(BaseModel):
    """Request to disconnect a Bluetooth device"""
    address: str

class BluetoothDeviceCreate(BaseModel):
    """Request to create/save a Bluetooth device to database"""
    name: str = Field(..., description="Device name")
    device_id: str = Field(..., description="Unique device identifier")
    mac_address: str = Field(..., description="MAC address of the device")
    calibration: Optional[str] = Field(None, description="Calibration settings")
    signal_strength: Optional[float] = Field(None, description="Signal strength in dBm")
    connected: bool = Field(False, description="Connection status")

class BluetoothDeviceUpdate(BaseModel):
    """Request to update a Bluetooth device"""
    name: Optional[str] = Field(None, description="Device name")
    device_id: Optional[str] = Field(None, description="Unique device identifier")
    calibration: Optional[str] = Field(None, description="Calibration settings")
    next_calibration_date: Optional[str] = Field(None, description="Next calibration date (YYYY-MM-DD)")

class BluetoothDeviceResponse(BaseModel):
    """Response model for Bluetooth device"""
    id: int
    name: str
    device_id: str
    mac_address: str
    calibration: Optional[str]
    signal_strength: Optional[float]
    connected: bool
    created_at: str
    next_calibration_date: Optional[str] = None
    instrument_code: Optional[str] = None

    class Config:
        from_attributes = True


def _bluetooth_device_response(db_device: BluetoothDevice, instrument_code: Optional[str] = None) -> BluetoothDeviceResponse:
    return BluetoothDeviceResponse(
        id=db_device.id,
        name=db_device.name,
        device_id=db_device.device_id,
        mac_address=db_device.mac_address,
        calibration=db_device.calibration,
        signal_strength=db_device.signal_strength,
        connected=db_device.connected,
        created_at=db_device.created_at.isoformat(),
        next_calibration_date=_next_calibration_date_to_str(db_device.next_calibration_date),
        instrument_code=instrument_code,
    )


@router.post("/scan", response_model=List[DeviceInfo])
async def scan_devices():
    """
    Scan for nearby Bluetooth devices.
    Returns a list of discovered devices with address, name, and signal strength.
    """
    try:
        logger.info("Starting Bluetooth device scan...")
        
        # Dictionary to store device info with RSSI
        discovered_devices = {}
        
        # Detection callback to capture RSSI
        def detection_callback(device, advertisement_data):
            if device.address not in discovered_devices:
                discovered_devices[device.address] = {
                    "address": device.address,
                    "name": device.name or advertisement_data.local_name or "Unknown Device",
                    "rssi": advertisement_data.rssi,
                    "connected": device.address in connected_devices
                }
                logger.info(f"Found device: {discovered_devices[device.address]['name']} ({device.address})")
        
        # Create scanner with callback
        scanner = BleakScanner(detection_callback)
        
        # Scan for 5 seconds (reduced from 10)
        await scanner.start()
        await asyncio.sleep(5.0)
        await scanner.stop()
        
        # Convert to response format
        discovered = [DeviceInfo(**device_info) for device_info in discovered_devices.values()]
        
        logger.info(f"Scan complete. Found {len(discovered)} devices")
        
        # If no devices found, return some mock devices for testing
        if len(discovered) == 0:
            logger.info("No devices found, returning mock data for testing")
            mock_devices = [
                DeviceInfo(
                    address="00:11:22:33:44:55",
                    name="Mock Device 1",
                    rssi=-65,
                    connected=False
                ),
                DeviceInfo(
                    address="AA:BB:CC:DD:EE:FF",
                    name="Mock Device 2",
                    rssi=-78,
                    connected=False
                )
            ]
            return mock_devices
        
        return discovered
        
    except Exception as e:
        logger.error(f"Error scanning for Bluetooth devices: {e}")
        # Return mock data on error for testing
        mock_devices = [
            DeviceInfo(
                address="00:11:22:33:44:55",
                name="Mock Device (Error Mode)",
                rssi=-65,
                connected=False
            )
        ]
        return mock_devices


@router.post("/connect")
async def connect_device(request: ConnectRequest):
    """
    Connect to a Bluetooth device by address.
    """
    try:
        address = request.address
        logger.info(f"Attempting to connect to device: {address}")
        
        # Check if already connected
        if address in connected_devices:
            logger.info(f"Device {address} is already connected")
            return {
                "success": True,
                "message": f"Device {request.name or address} is already connected",
                "address": address
            }
        
        # Create client and connect
        client = BleakClient(address)
        await client.connect()
        
        if client.is_connected:
            connected_devices[address] = client
            logger.info(f"Successfully connected to {address}")

            # First, try to get a live measurement value via notifications on the
            # known measurement characteristic (user-provided monitor_data logic).
            measurement_char_uuid = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
            characteristic_value: Optional[str] = None
            characteristic_uuid: Optional[str] = None

            try:
                live_value = await _read_notification_sample(client, measurement_char_uuid, timeout=2.0)
                if live_value is not None:
                    characteristic_value = live_value
                    characteristic_uuid = measurement_char_uuid
                    logger.info(
                        f"Notification measurement from {measurement_char_uuid}: {characteristic_value}"
                    )
            except Exception as e:
                logger.warning(
                    f"Could not get notification sample from measurement characteristic: {e}"
                )

            # Fallback: if we didn't get a notification, read the first readable characteristic
            if characteristic_value is None:
                try:
                    # Support both Bleak 2.x (get_services()) and older (services property)
                    if hasattr(client, "get_services") and callable(getattr(client, "get_services")):
                        svc_collection = await client.get_services()
                    else:
                        svc_collection = getattr(client, "services", None)

                    service_list = getattr(svc_collection, "services", None)
                    if service_list is not None and hasattr(service_list, "values"):
                        services_iter = service_list.values()
                    elif svc_collection is not None:
                        services_iter = (
                            svc_collection
                            if hasattr(svc_collection, "__iter__")
                            and not isinstance(svc_collection, (str, bytes))
                            else []
                        )
                    else:
                        services_iter = []

                    # Prefer application / vendor characteristics over generic ones
                    ignored_service_prefixes = {"00001800", "00001801"}  # Generic Access, Generic Attribute
                    ignored_char_prefixes = {"00002a00", "00002a01"}  # Device Name, Appearance

                    for service in services_iter:
                        service_uuid = str(getattr(service, "uuid", "")).lower()
                        if any(service_uuid.startswith(p) for p in ignored_service_prefixes):
                            continue

                        for char in service.characteristics:
                            char_uuid_str = str(getattr(char, "uuid", "")).lower()
                            if any(char_uuid_str.startswith(p) for p in ignored_char_prefixes):
                                continue

                            if "read" in getattr(char, "properties", []):
                                raw = await client.read_gatt_char(char.uuid)
                                characteristic_uuid = str(char.uuid)
                                try:
                                    characteristic_value = raw.decode("utf-8").strip()
                                except Exception:
                                    characteristic_value = raw.hex()
                                logger.info(
                                    f"Read characteristic {char.uuid}: {characteristic_value}"
                                )
                                break

                        if characteristic_value is not None:
                            break
                except Exception as e:
                    logger.warning(f"Could not read BLE characteristic: {e}")

            return {
                "success": True,
                "message": f"Connected to {request.name or address}",
                "address": address,
                "connected": True,
                "characteristic_value": characteristic_value,
                "characteristic_uuid": characteristic_uuid,
            }
        else:
            raise Exception("Failed to establish connection")
            
    except Exception as e:
        logger.error(f"Error connecting to device {request.address}: {e}")
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")


@router.post("/disconnect")
async def disconnect_device(request: DisconnectRequest):
    """
    Disconnect a Bluetooth device by address.
    """
    try:
        address = request.address
        logger.info(f"Disconnecting device: {address}")
        
        if address not in connected_devices:
            logger.warning(f"Device {address} is not in connected devices list")
            return {
                "success": True,
                "message": "Device was not connected",
                "address": address
            }
        
        # Get client and disconnect
        client = connected_devices[address]
        await client.disconnect()
        
        # Remove from connected devices
        del connected_devices[address]
        
        logger.info(f"Successfully disconnected {address}")
        return {
            "success": True,
            "message": f"Disconnected from {address}",
            "address": address,
            "connected": False
        }
        
    except Exception as e:
        logger.error(f"Error disconnecting device {request.address}: {e}")
        raise HTTPException(status_code=500, detail=f"Disconnect failed: {str(e)}")


@router.websocket("/stream/{address}")
async def stream_bluetooth_data(websocket: WebSocket, address: str, char_uuid: str):
    """
    WebSocket endpoint to stream continuous notifications from a BLE characteristic.
    Requires the device to already be connected via /connect.
    """
    await websocket.accept()
    
    if address not in connected_devices:
        logger.warning(f"WebSocket stream failed: device {address} not connected")
        await websocket.close(code=1008, reason="Device not connected")
        return
        
    client = connected_devices[address]
    if not client.is_connected:
        logger.warning(f"WebSocket stream failed: device {address} is disconnected")
        await websocket.close(code=1008, reason="Device not connected")
        return

    def notification_handler(sender: int, data: bytearray):
        try:
            val = data.decode('utf-8').strip()
        except Exception:
            val = data.hex()
        # Schedule the send on the event loop
        asyncio.create_task(websocket.send_json({"value": val}))

    try:
        await client.start_notify(char_uuid, notification_handler)
        logger.info(f"Started streaming notifications for {address} on {char_uuid}")
        
        # Keep connection open until client disconnects
        while True:
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {address}")
    except Exception as e:
        logger.error(f"WebSocket error for {address}: {e}")
    finally:
        try:
            if client.is_connected:
                await client.stop_notify(char_uuid)
                logger.info(f"Stopped notifications for {address} on {char_uuid}")
        except Exception as e:
            logger.warning(f"Error stopping notifications: {e}")
@router.get("/connected", response_model=List[DeviceInfo])
async def get_connected_devices():
    """
    Get list of currently connected Bluetooth devices.
    """
    devices = []
    for address, client in connected_devices.items():
        if client.is_connected:
            devices.append(DeviceInfo(
                address=address,
                name="Connected Device",  # You can store names in a database
                connected=True
            ))
    return devices


@router.get("/device/{address}/services")
async def get_device_services(address: str):
    """
    Get GATT services for a connected device.
    Useful for discovering measurement characteristics.
    """
    try:
        if address not in connected_devices:
            raise HTTPException(status_code=404, detail="Device not connected")
        
        client = connected_devices[address]
        if not client.is_connected:
            raise HTTPException(status_code=400, detail="Device is no longer connected")
        
        # Get services (support both Bleak 2.x get_services() and older .services property)
        if hasattr(client, "get_services") and callable(getattr(client, "get_services")):
            svc_collection = await client.get_services()
        else:
            svc_collection = getattr(client, "services", None)
        if getattr(svc_collection, "services", None) is not None and hasattr(svc_collection.services, "values"):
            services_iter = svc_collection.services.values()
        elif svc_collection is not None and hasattr(svc_collection, "__iter__") and not isinstance(svc_collection, (str, bytes)):
            services_iter = svc_collection
        else:
            services_iter = []
        service_list = []
        for service in services_iter:
            characteristics = []
            for char in service.characteristics:
                characteristics.append({
                    "uuid": char.uuid,
                    "description": char.description,
                    "properties": char.properties
                })
            
            service_list.append({
                "uuid": service.uuid,
                "description": service.description,
                "characteristics": characteristics
            })
        
        return {
            "address": address,
            "services": service_list
        }
        
    except Exception as e:
        logger.error(f"Error getting services for {address}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devices", response_model=BluetoothDeviceResponse)
async def save_device_to_database(device: BluetoothDeviceCreate, db: Session = Depends(get_db)):
    """
    Save a Bluetooth device to the database.
    Same MAC as an existing row: idempotent update/return (retries & re-register flows).
    New MAC requires a unique device_id.
    """
    try:
        mac_normalized = _normalize_mac(device.mac_address)
        device_id = device.device_id.strip()

        mac_key = sql_func.upper(sql_func.replace(BluetoothDevice.mac_address, "-", ":"))
        by_mac = db.query(BluetoothDevice).filter(mac_key == mac_normalized).first()
        if by_mac:
            by_mac.name = device.name
            by_mac.mac_address = mac_normalized
            if device.signal_strength is not None:
                by_mac.signal_strength = device.signal_strength
            by_mac.connected = device.connected
            if device.calibration is not None:
                by_mac.calibration = device.calibration
            if device_id != by_mac.device_id:
                conflict = db.query(BluetoothDevice).filter(
                    BluetoothDevice.device_id == device_id,
                    BluetoothDevice.id != by_mac.id,
                ).first()
                if conflict:
                    raise HTTPException(
                        status_code=400,
                        detail="Device ID is already assigned to another Bluetooth device",
                    )
                by_mac.device_id = device_id
            db.commit()
            db.refresh(by_mac)
            logger.info("Bluetooth device save (existing MAC): %s (%s)", by_mac.name, by_mac.device_id)
            return _bluetooth_device_response(by_mac)

        dup_id = db.query(BluetoothDevice).filter(BluetoothDevice.device_id == device_id).first()
        if dup_id:
            raise HTTPException(
                status_code=400,
                detail="Device ID is already assigned to another Bluetooth device",
            )

        db_device = BluetoothDevice(
            name=device.name,
            device_id=device_id,
            mac_address=mac_normalized,
            calibration=device.calibration,
            signal_strength=device.signal_strength,
            connected=device.connected,
        )

        db.add(db_device)
        db.commit()
        db.refresh(db_device)

        logger.info(f"Saved Bluetooth device to database: {device.name} ({device_id})")

        return _bluetooth_device_response(db_device)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving device to database: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save device: {str(e)}")


@router.get("/devices", response_model=List[BluetoothDeviceResponse])
async def get_saved_devices(db: Session = Depends(get_db)):
    """
    Get all saved Bluetooth devices from the database.
    """
    try:
        devices = db.query(BluetoothDevice).order_by(BluetoothDevice.id.asc()).all()

        # Build a MAC -> instrument_code lookup from the library
        mac_list = [d.mac_address for d in devices if d.mac_address]
        lib_rows = (
            db.query(LibraryInstrument.equipment_no, LibraryInstrument.instrument_code)
            .filter(LibraryInstrument.equipment_no.in_(mac_list))
            .all()
        ) if mac_list else []
        mac_to_code: dict = {r.equipment_no: r.instrument_code for r in lib_rows}

        return [
            _bluetooth_device_response(device, instrument_code=mac_to_code.get(device.mac_address))
            for device in devices
        ]

    except Exception as e:
        logger.error(f"Error retrieving devices from database: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve devices: {str(e)}")


@router.patch("/devices/{device_pk}", response_model=BluetoothDeviceResponse)
async def update_device(device_pk: int, update: BluetoothDeviceUpdate, db: Session = Depends(get_db)):
    """
    Update a Bluetooth device by primary key id.
    """
    try:
        device = db.query(BluetoothDevice).filter(BluetoothDevice.id == device_pk).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        if update.name is not None:
            device.name = update.name
        if update.device_id is not None:
            existing = db.query(BluetoothDevice).filter(
                BluetoothDevice.device_id == update.device_id,
                BluetoothDevice.id != device_pk
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Another device with this device_id already exists")
            device.device_id = update.device_id
        if update.calibration is not None:
            device.calibration = update.calibration
        if update.next_calibration_date is not None:
            device.next_calibration_date = update.next_calibration_date
        db.commit()
        db.refresh(device)
        return _bluetooth_device_response(device)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating device: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update device: {str(e)}")


@router.delete("/devices/{device_id}")
async def delete_device_from_database(device_id: str, db: Session = Depends(get_db)):
    """
    Delete a Bluetooth device from the database.
    """
    try:
        device = db.query(BluetoothDevice).filter(BluetoothDevice.device_id == device_id).first()
        
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        # Disconnect if connected
        if device.mac_address in connected_devices:
            try:
                await connected_devices[device.mac_address].disconnect()
                del connected_devices[device.mac_address]
            except:
                pass  # Ignore disconnection errors
        
        db.delete(device)
        db.commit()
        
        logger.info(f"Deleted Bluetooth device from database: {device_id}")
        
        return {"message": "Device deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting device from database: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete device: {str(e)}")


# Background task to monitor connections
async def monitor_connections():
    """Background task to monitor and clean up disconnected devices"""
    while True:
        await asyncio.sleep(30)  # Check every 30 seconds
        
        disconnected = []
        for address, client in list(connected_devices.items()):
            if not client.is_connected:
                disconnected.append(address)
                logger.info(f"Device {address} disconnected (detected in monitoring)")
        
        # Remove disconnected devices
        for address in disconnected:
            del connected_devices[address]
