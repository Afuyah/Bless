from datetime import datetime, timedelta, time
import pytz

def get_kenya_today_range():
    tz = pytz.timezone("Africa/Nairobi")
    now = datetime.now(tz)
    start = tz.localize(datetime.combine(now.date(), time.min))
    end = tz.localize(datetime.combine(now.date(), time.max))
    return start, end
