from flask import Flask,render_template
from threading import Thread

app = Flask(__name__)

#Function returns 'ALive' while running the program
@app.route('/')
def home():
    return "Bot is running!", 200

def run():
    app.run(host='0.0.0.0', port=5000)

def keep_alive():
    t = Thread(target=run)
    t.start()
