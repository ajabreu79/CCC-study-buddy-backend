# Copyright (c) 2024.
# -*-coding:utf-8 -*-
"""
@file: TtsStream.py
@author: Jerry(Ruihuang)Yang
@email: rxy216@case.edu
@time: 3/1/24 19:30
"""
import requests
import os

import time
from dotenv import load_dotenv


class TtsStream:
    """
    TtsStream: Text-to-Speech streaming with Deepgram API.
    """
    # Define the API endpoint
    URL = "https://api.deepgram.com/v1/speak?model=aura-arcas-en"
    TTS_AUDIO_CACHE_FOLDER = "tts_audio_cache"

    def __init__(self, tts_session_id: str):
        self.API_KEY = os.getenv("DEEPGRAM_API_KEY")
        self.tts_session_id = tts_session_id

    def stream_tts(self, text: str, chunk_id: str):
        # Define the headers
        headers = {
            "Authorization": f"Token {self.API_KEY}",
            "Content-Type": "application/json"
        }

        # Define the payload
        payload = {
            "text": text,
        }

        # Make the POST request
        response = requests.post(self.URL, headers=headers, json=payload)

        # Check if the request was successful
        if response.status_code == 200:
            # Save the response content to a file
            with open(f"./{self.TTS_AUDIO_CACHE_FOLDER}/{self.tts_session_id}_{chunk_id}.mp3", "wb") as f:
                f.write(response.content)
            print("TTS file saved successfully.")
        else:
            print(f"Error: {response.status_code} - {response.text}")
