-- Add next_calibration_date column to bluetooth_devices table
ALTER TABLE bluetooth_devices 
ADD COLUMN next_calibration_date VARCHAR(10);

-- Add comment to describe the column format
COMMENT ON COLUMN bluetooth_devices.next_calibration_date IS 'Next calibration date in YYYY-MM-DD format';
