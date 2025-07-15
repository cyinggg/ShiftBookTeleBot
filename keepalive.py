from flask import Flask,render_template
from threading import Thread

app = Flask(__name__)

#Function returns 'ALive' while running the program
@app.route('/')
def home():
    return "Bot is running!", 200

if __name__ == "__main__":
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
