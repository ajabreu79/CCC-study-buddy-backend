# Copyright (c) 2024.
# -*-coding:utf-8 -*-
"""
@file: SttApiKey.py
@author: Jerry(Ruihuang)Yang
@email: rxy216@case.edu
@time: 3/22/24 00:29
"""
import os

import requests
from pydantic import BaseModel


class SttApiKeyResponse(BaseModel):
    status: str  # "success" or "fail"
    error_message: str | None = None
    key: str


class SttApiKey:
    """
    SttApiKey: Generate a new API key for Deepgram Speech-to-Text.
    This key will be sent to the user for use in the client-side.
    The only scope is "usage:write".
    """

    def __init__(self):
        self.DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
        self.DEEPGRAM_PROJECT_ID = os.getenv("DEEPGRAM_PROJECT_ID")

    def generate_key(self):
        """
        Generate a new API key for the user.
        :return:
        """
        url = f"https://api.deepgram.com/v1/projects/{self.DEEPGRAM_PROJECT_ID}/keys"

        payload = {
            "comment": "user_id",
            "scopes": ["usage:write"],
            "tags": ["user_side"],
            "time_to_live_in_seconds": 2000
        }
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Token {self.DEEPGRAM_API_KEY}"
        }

        response = requests.post(url, json=payload, headers=headers)

        # load the response content as a dictionary
        response_dict = response.json()
        # extract the API key from the dictionary
        api_key = response_dict.get("key")
        api_key_id = response_dict.get("api_key_id")
        return api_key, api_key_id
