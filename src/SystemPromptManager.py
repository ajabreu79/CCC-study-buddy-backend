# Copyright (c) 2024.
# -*-coding:utf-8 -*-
"""
@file: SystemPromptManager.py
@author: Jerry(Ruihuang)Yang, Jiana Kambo
@email: rxy216@case.edu, jxk1403@case.edu
@time: 3/1/24 19:49
"""


import os

class SystemPromptManager:
    """
    SystemPromptManager: Manages system prompts for the chat system.
    """

    SYSTEM_PROMPT_CACHE_FOLDER = "system_prompt_cache"

    def __init__(self):
        # Ensure the system prompt cache folder exists
        os.makedirs(self.SYSTEM_PROMPT_CACHE_FOLDER, exist_ok=True)

    def set_system_prompt(self, assistant_id: str, system_prompt: str):
        """
        Set the system prompt for a given assistant id, Save the system prompt to a file with the assistant_id as the
        filename.
        :param assistant_id: The ID of the assistant.
        :param system_prompt: The system prompt to set.
        :return: None
        """
        prompt_file_path = os.path.join(self.SYSTEM_PROMPT_CACHE_FOLDER, f"{assistant_id}.txt")
        with open(prompt_file_path, "w") as prompt_file:
            prompt_file.write(system_prompt)

    def get_system_prompt(self, assistant_id: str) -> str:
        """
        Get the system prompt for a given assistant id.
        :param assistant_id: The ID of the assistant.
        :return: The system prompt.
        """
        prompt_file_path = os.path.join(self.SYSTEM_PROMPT_CACHE_FOLDER, f"{assistant_id}.txt")
        if os.path.exists(prompt_file_path):
            with open(prompt_file_path, "r") as prompt_file:
                return prompt_file.read().strip()
        else:
            return ""
