#!/usr/bin/env python3

import json
from ollama import chat
from pydantic import BaseModel, Field
import os
from pypinyin import pinyin
import requests
import subprocess
import sys
import time


def anki_is_running():
    try:
        requests.post(ANKI_CONNECT_URL, json={"action": "version", "version": 6}, timeout=2)
        return True
    except requests.exceptions.ConnectionError:
        return False


def wait_for_anki(timeout=30, interval=0.5):
    start = time.time()
    while time.time() - start < timeout:
        if anki_is_running():
            return True
        time.sleep(interval)
    return False


ANKI_CONNECT_URL = "http://127.0.0.1:8765"
WORD_DECK = "Extra"
IDIOM_DECK = "Idioms & Set Phrases"
NOTE_TYPE = "HSK+ (extra)"


def to_pinyin(text):
    return " ".join(p[0] for p in pinyin(text))


def is_chinese(text):
    return all('\u4e00' <= char <= '\u9fff' for char in text)


def invoke(action, **params):
    payload = {"action": action, "version": 6, "params": params}
    resp = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
    result = resp.json()
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result["result"]


def add_to_anki(word, data, model_name=NOTE_TYPE):
    deck_name = IDIOM_DECK if data["is_chengyu"] else WORD_DECK
    note = {
        "deckName": deck_name,
        "modelName": model_name,
        "fields": {
            "Simplified": word,
            "Traditional": "",
            "Pinyin.1": to_pinyin(word),
            "Pinyin.2": "",
            "Meaning": data["meaning_english"],
            "Part of speech": data["part_of_speech_english"],
            "Audio": "",
            "Homophone": "",
            "Homograph": "",
            "SentenceSimplified": data["sentencesimplified"],
            "SentenceTraditional": "",
            "SentenceSimplifiedCloze": "",
            "SentenceTraditionalCloze": "",
            "SentencePinyin.1": data["sentencepinyin"],
            "SentencePinyin.2": "",
            "SentenceMeaning": data["sentencemeaning_english"],
            "SentenceAudio": "",
            "SentenceImage": "",
        },
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    }
    try:
        note_id = invoke("addNote", note=note)
    except requests.exceptions.ConnectionError:
        print("Error: Anki is closed.")
        sys.exit(0)
    except RuntimeError:
        print(f'"{word}" already exists in {deck_name} — skipped.')
        return
    print(f"Added '{word}' as note {note_id} to {deck_name}.")
    return note_id


class ExtraNote(BaseModel):
    is_chengyu: bool = Field(description="True if this vocabulary word is an idiom or set phrase, false otherwise")
    meaning_english: str = Field(description="The meaning of the Mandarin vocabulary word in English")
    part_of_speech_english: str = Field(description="The part(s) of speech of this word in English")
    sentencesimplified: str = Field(description="An example sentence including the word in simplified Mandarin")
    sentencemeaning_english: str = Field(description="The English translation of the example sentence")


class RegenerateExampleSentence(BaseModel):
    sentencesimplified: str = Field(description="An example sentence including the word in simplified Mandarin")
    sentencemeaning_english: str = Field(description="The English translation of the example sentence")


def generate_card(vocab_word):

    response = chat(
        model='qwen3.5:4b',  # Ensure you use a model that supports structured JSON
        messages=[
            {
                'role': 'user',
                'content': f'For the Mandarin word "{vocab_word}", provide: '
                f'(1) whether this is a chengyu, '
                f'(2) meaning — written in English, '
                f'(3) part of speech — written in English, '
                f'(4) an example sentence in simplified Chinese, '
                f'(5) the English translation of that example sentence.',
            },
        ],
        # Pass the Pydantic schema into the format argument
        format=ExtraNote.model_json_schema(),
        options={'temperature': 0},  # Low temperature ensures strict format adherence
        think=False,  # turn off extended reasoning
    )
    raw_content = response.message.content
    data = json.loads(raw_content)
    data["sentencepinyin"] = to_pinyin(data["sentencesimplified"])
    data["part_of_speech_english"] = data["part_of_speech_english"].lower()  # because I prefer lowercase

    # print(json.dumps(data, indent=2, ensure_ascii=False))

    while True:
        print(f"Deck: { IDIOM_DECK if data['is_chengyu'] else WORD_DECK}")
        print(f"Word: {vocab_word}")
        print(f"Meaning: {data["meaning_english"]}")
        print(f"Part of Speech: {data["part_of_speech_english"]}")
        print(f"Example Sentence: {data["sentencesimplified"]}")
        print(f"Sentence Meaning: {data["sentencemeaning_english"]}")
        menu = f"\n0. Cancel\n1. Add to {IDIOM_DECK if data["is_chengyu"] else WORD_DECK}\n2. Switch Deck\n3. Edit English meaning\n4. Edit part of speech\n5. Regenerate example sentence\n6. Type in example sentence manually"
        print(menu)
        user_input = input("> ").strip()
        if user_input == "0":
            return
        elif user_input == "1":
            add_to_anki(vocab_word, data)
            return
        elif user_input == "2":
            data["is_chengyu"] = not data["is_chengyu"]
        elif user_input == "3":
            data["meaning_english"] = input("Type in new meaning: ")
        elif user_input == "4":
            data["part_of_speech_english"] = input("Type in new part of speech: ")
        elif user_input == "5":
            response = chat(
                model='qwen3.5:4b',  # Ensure you use a model that supports structured JSON
                messages=[
                    {
                        'role': 'user',
                        'content': f'For the Mandarin word "{vocab_word}", provide: '
                        f'(1) an example sentence in simplified Chinese, '
                        f'(2) the English translation of that example sentence.'
                        f'Make sure it is meaningfully different from the last one: "{data["sentencesimplified"]}", as the user has rejected that one.'
                    },
                ],
                # Pass the Pydantic schema into the format argument
                format=RegenerateExampleSentence.model_json_schema(),
                options={'temperature': 0},  # Low temperature ensures strict format adherence
                think=False,  # turn off extended reasoning
            )
            new_example = json.loads(response.message.content)
            data["sentencesimplified"] = new_example["sentencesimplified"]
            data["sentencepinyin"] = to_pinyin(data["sentencesimplified"])
            data["sentencemeaning_english"] = new_example["sentencemeaning_english"]
        elif user_input == "6":
            data["sentencesimplified"] = input("Type in new example sentence: ")
            data["sentencepinyin"] = to_pinyin(data["sentencesimplified"])
            data["sentencemeaning_english"] = input("Type in the English translation (or /s for machine translation): ")
            if data["sentencemeaning_english"].strip().lower() == "/s":
                response = chat(
                    model='qwen3.5:4b',
                    messages=[
                        {
                            'role': 'system',
                            'content': 'Translate this sentence to English. Do not return anything else.',
                        },
                        {
                            'role': 'user',
                            'content': data["sentencesimplified"],

                        },
                    ],
                    options={'temperature': 0},  # Low temperature ensures strict format adherence
                    think=False,  # turn off extended reasoning
                )
                data["sentencemeaning_english"] = response.message.content


if __name__ == "__main__":
    if len(sys.argv) > 1:
        anki_path = "/Applications/Anki.app"

        if not anki_is_running():
            if os.path.exists(anki_path) or anki_path == "anki":
                launch_cmd = ['open', '-g', anki_path] if anki_path != "anki" else ['anki']
                subprocess.Popen(launch_cmd)
                if not wait_for_anki():
                    print("Timed out waiting for Anki to start.")
                    sys.exit(1)
            else:
                print("Anki executable not found at the specified path.")
                sys.exit(1)
        for i in range(1, len(sys.argv)):
            if len(sys.argv) > 2:
                print(f"====={i} of {len(sys.argv) - 1}=====")
            if is_chinese(sys.argv[i]):
                generate_card(sys.argv[i])
            else:
                print(f'"{sys.argv[i]}" is not Mandarin Chinese. Skipping...')
    else:
        print("Which word do you want to add into Anki?")
