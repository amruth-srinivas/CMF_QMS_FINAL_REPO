"""
Bluetooth device model for database storage.
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float
from sqlalchemy.sql import func
from app.database import Base


class BluetoothDevice(Base):
    """Bluetooth device stored in database"""
    __tablename__ = "bluetooth_devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    device_id = Column(String(100), nullable=False, unique=True, index=True)
    mac_address = Column(String(17), nullable=False, unique=True, index=True)
    calibration = Column(Text, nullable=True)
    signal_strength = Column(Float, nullable=True)  # RSSI in dBm
    connected = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    next_calibration_date = Column(String(10), nullable=True)  # YYYY-MM-DD format

    def __repr__(self):
        return f"<BluetoothDevice(id={self.id}, name='{self.name}', device_id='{self.device_id}')>"
