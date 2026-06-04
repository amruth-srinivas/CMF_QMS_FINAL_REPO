
import random
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, SessionLocal
from app.models.instrument_setup import InstrumentSetupCategory, LibraryInstrument

# Configuration
MANUFACTURERS = ["Mitutoyo", "Starrett", "Mahr", "Tesa", "Fowler", "Insize", "Sylvac"]
LOCATIONS = ["Quality Lab", "Main Tool Crib", "Assembly Line A", "Inspection Room 2", "Calibration Dept"]
STATUSES = ["Active", "Active", "Active", "Active", "In Repair", "In Calibration"]

HIERARCHY = {
    "Linear Measurement": [
        "Vernier Caliper", "Micrometer", "Height Gauge", "Depth Gauge"
    ],
    "Bore/Internal Measurement": [
        "Bore Gauge", "Dial Bore Gauge"
    ],
    "Comparative Instruments": [
        "Dial Indicator", "Lever Dial"
    ],
    "Precision Standards": [
        "Slip Gauges", "Gauge Blocks"
    ],
    "Go/No-Go Gauges": [
        "Plug Gauge", "Ring Gauge", "Thread Gauge"
    ],
    "Surface & Geometry": [
        "Surface Plate", "Bevel Protractor", "Radius Gauge"
    ]
}

def get_random_date(days_ago_min=0, days_ago_max=365):
    days = random.randint(days_ago_min, days_ago_max)
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

def get_next_cal_date(last_cal_str, interval_months):
    last_cal = datetime.strptime(last_cal_str, "%Y-%m-%d")
    next_cal = last_cal + timedelta(days=interval_months * 30)
    return next_cal.strftime("%Y-%m-%d")

def seed():
    db = SessionLocal()
    try:
        print("Cleaning existing instrument data...")
        db.query(LibraryInstrument).delete()
        db.query(InstrumentSetupCategory).delete()
        db.commit()

        print("Seeding categories and instruments...")
        
        for parent_name, children in HIERARCHY.items():
            parent_cat = InstrumentSetupCategory(name=parent_name)
            db.add(parent_cat)
            db.flush() # Get parent_cat.id

            for child_name in children:
                child_cat = InstrumentSetupCategory(name=child_name, parent_id=parent_cat.id)
                db.add(child_cat)
                db.flush()

                # Generate 20+ instruments for this leaf category
                num_items = random.randint(20, 25)
                for i in range(num_items):
                    mfr = random.choice(MANUFACTURERS)
                    interval = random.choice([6, 12, 24])
                    last_cal = get_random_date(0, 300)
                    next_cal = get_next_cal_date(last_cal, interval)
                    
                    # Generate a consistent Asset Tag
                    short_code = "".join([c for c in child_name if c.isupper()]) or child_name[:3].upper()
                    asset_tag = f"{short_code}-{parent_name[:1].upper()}{random.randint(1000, 9999)}"
                    
                    # Specs based on category name
                    range_val = "0-150 mm" if "Caliper" in child_name else "0-25 mm" if "Micrometer" in child_name else "N/A"
                    res_val = "0.01 mm" if "Digital" in child_name or i % 2 == 0 else "0.02 mm"
                    
                    instr = LibraryInstrument(
                        category_id=child_cat.id,
                        instrument_code=asset_tag,
                        instrument_name=f"{mfr} {child_name}",
                        manufacturer=mfr,
                        model_number=f"{mfr[:2].upper()}-{random.randint(100, 999)}",
                        serial_number=f"SN{random.randint(100000, 999999)}",
                        range=range_val,
                        resolution=res_val,
                        accuracy="±0.01 mm",
                        last_calibration_date=last_cal,
                        calibration=next_cal,
                        calibration_interval=interval,
                        status=random.choice(STATUSES),
                        location=random.choice(LOCATIONS),
                        available_qty=1,
                        equipment_no=asset_tag # Keep in sync for Bluetooth/Legacy
                    )
                    db.add(instr)
            
            db.commit()
            print(f"  - Finished {parent_name}")

        print("Seeding complete successfully!")

    except Exception as e:
        print(f"Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed()
