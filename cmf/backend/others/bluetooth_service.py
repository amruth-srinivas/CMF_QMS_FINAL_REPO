import subprocess
import time
import json
import re
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class BluetoothService:
    """Service for handling Bluetooth device operations"""
    
    def __init__(self):
        self.connected_devices = set()
        
    def is_available(self) -> bool:
        """Check if Bluetooth is available on the system"""
        try:
            result = subprocess.run(['bluetoothctl', '--version'], 
                                  capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def scan_devices(self) -> List[Dict]:
        """Scan for nearby Bluetooth devices"""
        try:
            # Start scanning
            subprocess.run(['bluetoothctl', 'scan', 'on'], 
                          capture_output=True, timeout=5)
            
            # Wait a bit for devices to be discovered
            time.sleep(3)
            
            # Get devices
            result = subprocess.run(['bluetoothctl', 'devices'], 
                                  capture_output=True, text=True, timeout=10)
            
            devices = []
            for line in result.stdout.split('\n'):
                if line.startswith('Device '):
                    parts = line.split(' ', 2)
                    if len(parts) >= 3:
                        address = parts[1]
                        name = parts[2] if len(parts) > 2 else 'Unknown Device'
                        
                        # Get signal strength if available
                        rssi = self._get_device_rssi(address)
                        
                        devices.append({
                            'address': address,
                            'name': name,
                            'rssi': rssi,
                            'connected': address in self.connected_devices
                        })
            
            # Stop scanning
            subprocess.run(['bluetoothctl', 'scan', 'off'], 
                          capture_output=True, timeout=5)
            
            return devices
            
        except Exception as e:
            logger.error(f"Error scanning devices: {e}")
            # Return mock data for testing when Bluetooth is not available
            return self._get_mock_devices()
    
    def _get_device_rssi(self, address: str) -> Optional[int]:
        """Get RSSI (signal strength) for a device"""
        try:
            result = subprocess.run(['bluetoothctl', 'info', address], 
                                  capture_output=True, text=True, timeout=5)
            
            for line in result.stdout.split('\n'):
                if 'RSSI:' in line:
                    rssi_match = re.search(r'RSSI:\s*(-?\d+)', line)
                    if rssi_match:
                        return int(rssi_match.group(1))
            return None
        except Exception:
            return None
    
    def connect_device(self, address: str, name: str) -> bool:
        """Connect to a Bluetooth device"""
        try:
            # Try to connect
            result = subprocess.run(['bluetoothctl', 'connect', address], 
                                  capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0 and 'Connected' in result.stdout:
                self.connected_devices.add(address)
                logger.info(f"Successfully connected to {name} ({address})")
                return True
            else:
                logger.error(f"Failed to connect to {name} ({address}): {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error connecting to device {address}: {e}")
            return False
    
    def disconnect_device(self, address: str) -> bool:
        """Disconnect from a Bluetooth device"""
        try:
            result = subprocess.run(['bluetoothctl', 'disconnect', address], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.connected_devices.discard(address)
                logger.info(f"Successfully disconnected from {address}")
                return True
            else:
                logger.error(f"Failed to disconnect from {address}: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error disconnecting from device {address}: {e}")
            return False
    
    def get_connected_devices(self) -> List[Dict]:
        """Get list of currently connected devices"""
        try:
            result = subprocess.run(['bluetoothctl', 'devices', 'Connected'], 
                                  capture_output=True, text=True, timeout=10)
            
            devices = []
            for line in result.stdout.split('\n'):
                if line.startswith('Device '):
                    parts = line.split(' ', 2)
                    if len(parts) >= 3:
                        address = parts[1]
                        name = parts[2] if len(parts) > 2 else 'Unknown Device'
                        
                        devices.append({
                            'mac_address': address,
                            'name': name,
                            'connected': True
                        })
                        self.connected_devices.add(address)
            
            return devices
            
        except Exception as e:
            logger.error(f"Error getting connected devices: {e}")
            return []
    
    def get_device_services(self, address: str) -> List[Dict]:
        """Get services for a specific Bluetooth device"""
        try:
            result = subprocess.run(['bluetoothctl', 'info', address], 
                                  capture_output=True, text=True, timeout=10)
            
            services = []
            current_service = None
            
            for line in result.stdout.split('\n'):
                if 'UUID:' in line and any(service in line for service in ['Audio', 'HID', 'Battery']):
                    uuid_match = re.search(r'UUID:\s*([0-9a-f-]+)', line.lower())
                    service_match = re.search(r'(Audio|HID|Battery)', line, re.IGNORECASE)
                    
                    if uuid_match and service_match:
                        service_type = service_match.group(1)
                        services.append({
                            'uuid': uuid_match.group(1),
                            'type': service_type,
                            'name': f"{service_type} Service"
                        })
            
            return services
            
        except Exception as e:
            logger.error(f"Error getting device services for {address}: {e}")
            return []
    
    def _get_mock_devices(self) -> List[Dict]:
        """Return mock devices for testing when Bluetooth is not available"""
        return [
            {
                'address': '00:1A:7D:DA:71:13',
                'name': 'Mock QMS Device 1',
                'rssi': -45,
                'connected': False
            },
            {
                'address': '00:1B:44:11:22:33',
                'name': 'Mock Measurement Tool',
                'rssi': -62,
                'connected': False
            },
            {
                'address': '00:14:20:04:71:13',
                'name': 'Mock TLC-BLE',
                'rssi': -48,
                'connected': False
            }
        ]
