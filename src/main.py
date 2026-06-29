from dotenv import load_dotenv

load_dotenv()

from src.scheduler import start_scheduler

if __name__ == "__main__":
    start_scheduler()
