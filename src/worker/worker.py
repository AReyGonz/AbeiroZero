import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fetch_meteogalicia():
    logger.info("Initiating MeteoGalicia 10-min ETL...")
    # Add robust try/except, requests with timeouts, and DB upsert logic here
    # Use SQLAlchemy's on_conflict_do_update for PostgreSQL to prevent duplicates

if __name__ == "__main__":
    scheduler = AsyncIOScheduler()
    # Runs exactly every 10 minutes, robust against overlapping jobs
    scheduler.add_job(fetch_meteogalicia, 'cron', minute='0,10,20,30,40,50', max_instances=1)
    
    logger.info("Starting AbeiroZero ETL Daemon...")
    scheduler.start()
    
    # Keep the daemon alive
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass