import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))

# Load environment variables from .env file
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'you-will-never-guess')  
    SQLALCHEMY_DATABASE_URI ='postgresql://postgres:WakpFCEZjrKOmisavwiSjjbVLSuqqjQB@junction.proxy.rlwy.net:40841/railway'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SOCKETIO_MESSAGE_QUEUE = None
