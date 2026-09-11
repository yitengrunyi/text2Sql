import os
import sys

from loguru import logger
from datetime import datetime, timedelta
from threading import Thread

project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logger.info("Project Path:", project_path)
sys.path.append(project_path)
action_path, action_file = os.path.split(os.path.abspath(__file__))

from handler.field_tag import sync_all_tags_data
from handler.update_user_data import update_user_date
from handler.query_recommend_user_stock import recommend_prediction_models, recommend_stock_by_user, \
    recommend_prediction_armmfv_models
from handler.update_rec_user_article_data import insert_alpha_rec_all_article


def get_sync_all_tags_data_time_range():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_time = today - timedelta(days=14)
    end_time = today
    return start_time.strftime('%Y-%m-%d %H:%M:%S'), end_time.strftime('%Y-%m-%d %H:%M:%S')


def get_update_user_date_range():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today - timedelta(days=1)
    end_date = today
    return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')


def get_last_full_hour_time_range():
    now = datetime.now()
    last_full_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    start_time = last_full_hour
    end_time = last_full_hour + timedelta(hours=1)
    return start_time.strftime('%Y-%m-%d %H:%M:%S'), end_time.strftime('%Y-%m-%d %H:%M:%S')


def get_yesterday_and_today_date_range():
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')


def run_sync_all_tags_data_one_hour():
    try:
        start_time, end_time = get_last_full_hour_time_range()
        logger.info(f"Starting sync_all_tags_data with start_time: {start_time}, end_time: {end_time}")
        sync_all_tags_data(start_time, end_time)
        logger.info("Finished sync_all_tags_data")
    except Exception as e:
        logger.error(f"Error in sync_all_tags_data: {e}")


def run_sync_all_tags_data():
    try:
        start_time, end_time = get_sync_all_tags_data_time_range()
        logger.info(f"Starting sync_all_tags_data with start_time: {start_time}, end_time: {end_time}")
        sync_all_tags_data(start_time, end_time)
        logger.info("Finished sync_all_tags_data")
    except Exception as e:
        logger.error(f"Error in sync_all_tags_data: {e}")


def run_update_user_date():
    try:
        start_date, end_date = get_update_user_date_range()
        logger.info(f"Starting update_user_date with start_date: {start_date}, end_date: {end_date}")
        update_user_date(start_date, end_date)
        logger.info("Finished update_user_date")
    except Exception as e:
        logger.error(f"Error in update_user_date: {e}")


def run_recommend_prediction_models():
    try:
        start_date, end_date = get_yesterday_and_today_date_range()
        logger.info(f"Starting recommend_prediction_models with start_date: {start_date}, end_date: {end_date}")
        recommend_prediction_models(start_date, end_date, 200, 10, 20)
        logger.info("Finished recommend_prediction_models")
    except Exception as e:
        logger.error(f"Error in recommend_prediction_models: {e}")


def run_recommend_prediction_armmfv_models():
    try:
        start_date = '2024-08-22'
        end_date = '2024-08-23'
        logger.info(f"Starting recommend_prediction_models with start_date: {start_date}, end_date: {end_date}")
        recommend_prediction_armmfv_models(start_date, end_date, 200, 10, 20)
        logger.info("Finished recommend_prediction_models")
    except Exception as e:
        logger.error(f"Error in recommend_prediction_models: {e}")

def run_recommend_stock_by_user():
    try:
        start_date, end_date = get_yesterday_and_today_date_range()
        logger.info(f"Starting recommend_stock_by_user with start_date: {start_date}, end_date: {end_date}")
        recommend_stock_by_user(start_date, end_date)
        logger.info("Finished recommend_stock_by_user")
    except Exception as e:
        logger.error(f"Error in recommend_stock_by_user: {e}")


def run_insert_alpha_rec_all_article():
    try:
        start_time, end_time = get_last_full_hour_time_range()
        logger.info(f"Starting insert_alpha_rec_all_article with start_time: {start_time}, end_time: {end_time}")
        insert_alpha_rec_all_article(start_time, end_time)
        logger.info("Finished insert_alpha_rec_all_article")
    except Exception as e:
        logger.error(f"Error in insert_alpha_rec_all_article: {e}")


if __name__ == "__main__":
    logger.info("Starting both processes...")

    # sync_thread = Thread(target=run_sync_all_tags_data)
    # update_thread = Thread(target=run_update_user_date)

    # sync_thread.start()
    # update_thread.start()

    # sync_thread.join()
    # update_thread.join()

    # logger.info("Both processes finished.")


    # logger.info("Starting the sequential process...")

    # run_sync_all_tags_data_one_hour()
    run_recommend_prediction_armmfv_models()
    # run_recommend_stock_by_user()
    # run_insert_alpha_rec_all_article()

    logger.info("All processes finished sequentially.")
