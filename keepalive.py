from flask import Flask
from threading import Thread

app = Flask(__name__)


#Function returns 'ALive' while running the program
@app.route('/')
def home():
    return "Bot is running!", 200

def keep_alive():
    t = Thread(target=run)
    t.start()
