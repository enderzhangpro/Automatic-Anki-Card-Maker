#!/usr/bin/env python3

import json
from ollama import chat
import os
from pycccedict.cccedict import CcCedict
from pydantic import BaseModel, Field
from pypinyin import pinyin
from pypinyin_dict.phrase_pinyin_data import large_pinyin
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
# WORD_NOTE_TYPE = "HSK+ (extra)"
WORD_NOTE_TYPE = "HSK+ Idioms"
IDIOM_NOTE_TYPE = "HSK+ Idioms"
CYAN = '\033[36m'
# GREEN = '\033[32m'
# YELLOW = '\033[33m'
# MAGENTA = '\033[35m'
# BRIGHT_RED = '\033[91m'
RED = '\033[31m'
BOLD = '\033[1m'
RESET = '\033[0m'
PRINT_WORD_DECK = f"{BOLD}{CYAN}{WORD_DECK}{RESET}"
PRINT_IDIOM_DECK = f"{BOLD}{RED}{IDIOM_DECK}{RESET}"

"""print(f"{BOLD}{CYAN}{WORD_DECK}{RESET}")
print(f"{BOLD}{GREEN}{WORD_DECK}{RESET}")
print(f"{BOLD}{YELLOW}{WORD_DECK}{RESET}")
print(f"{BOLD}{MAGENTA}{WORD_DECK}{RESET}")
print(f"{BOLD}{BRIGHT_RED}{WORD_DECK}{RESET}")
print(f"{BOLD}{RED}{WORD_DECK}{RESET}")"""


# to correct issues with the pinyin being generated incorrectly
large_pinyin.load()


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


def add_to_anki(word, data):
    deck_name = IDIOM_DECK if data["is_chengyu"] else WORD_DECK
    deck_name_color = PRINT_IDIOM_DECK if data["is_chengyu"] else PRINT_WORD_DECK
    if data["is_chengyu"]:
        model_name = IDIOM_NOTE_TYPE
    else:
        model_name = WORD_NOTE_TYPE
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
            "SentencePinyin.1": to_pinyin(data["sentencesimplified"]),
            "SentencePinyin.2": "",
            "SentenceMeaning": data["sentencemeaning_english"],
            "SentenceAudio": "",
            "SentenceImage": "",
            "Notes": data["notes"],
        },
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    }
    try:
        note_id = invoke("addNote", note=note)
    except requests.exceptions.ConnectionError:
        print("Error: Anki is closed.")
        sys.exit(0)
    except RuntimeError:
        print(f'"{word}" already exists in {deck_name_color} — skipped.')
        return
    print(f"Added '{word}' as note {note_id} to {deck_name_color}.")
    return note_id

class ExtraNoteWithoutVocabTranslation(BaseModel):
    is_chengyu: bool = Field(description="True if this vocabulary word is an idiom or set phrase, false otherwise")
    part_of_speech_english: str = Field(description="The part(s) of speech of this word in English")
    sentencesimplified: str = Field(description="An example sentence including the word in simplified Mandarin")
    sentencemeaning_english: str = Field(description="The English translation of the example sentence")

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

    dictionary_entry = cedict.get_entry(vocab_word)
    if dictionary_entry is not None:
        response = chat(
            model='qwen3.5:4b',  # Ensure you use a model that supports structured JSON
            messages=[
                {
                    'role': 'user',
                    'content': f'For the Mandarin word "{vocab_word}", provide: '
                    f'(1) whether this is a chengyu, '
                    f'(2) part of speech — written in English, '
                    f'(3) an example sentence in simplified Chinese, '
                    f'(4) the English translation of that example sentence.',
                },
            ],
            # Pass the Pydantic schema into the format argument
            format=ExtraNoteWithoutVocabTranslation.model_json_schema(),
            options={'temperature': 0},  # Low temperature ensures strict format adherence
            think=False,  # turn off extended reasoning
        )
        raw_content = response.message.content
        data = json.loads(raw_content)
        data["meaning_english"] = ""
        for i in range(len(dictionary_entry['definitions'])):
            data["meaning_english"] += dictionary_entry['definitions'][i]
            if i < len(dictionary_entry['definitions']) - 1:
                data["meaning_english"] += "; "
    else:
        print(f"{RED}Warning: '{vocab_word}' not found in Chinese-English CC-CEDICT dictionary. Reverting to LLM definition...{RESET}")
        response = chat(
            model='qwen3.5:4b',
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
            format=ExtraNote.model_json_schema(),
            options={'temperature': 0},
            think=False,
        )
        raw_content = response.message.content
        data = json.loads(raw_content)
    data["part_of_speech_english"] = data["part_of_speech_english"].lower()  # because I prefer lowercase
    data["notes"] = ""

    display_menu = True

    def replace_except_on_escape(original_value, prompt):
        user_input = input(prompt).strip()
        if user_input.lower() != "/q":
            return user_input
        return original_value

    # print(json.dumps(data, indent=2, ensure_ascii=False))

    while True:
        if display_menu:
            print(f"Deck: { PRINT_IDIOM_DECK if data['is_chengyu'] else PRINT_WORD_DECK}")
            print(f"Word: {vocab_word}")
            print(f"Meaning: {data["meaning_english"]}")
            print(f"Part of Speech: {data["part_of_speech_english"]}")
            print(f"Example Sentence: {data["sentencesimplified"]}")
            print(f"Sentence Meaning: {data["sentencemeaning_english"]}")
            if data["notes"] != "":
                print(f"Notes: {data["notes"]}")
            # menu = f"\n0. Cancel\n1. Add to {PRINT_IDIOM_DECK if data["is_chengyu"] else PRINT_WORD_DECK}\n2. Switch Deck\n3. Edit English meaning\n4. Edit part of speech\n5. Regenerate example sentence\n6. Type in example sentence manually"
            # menu = f"\n0. Cancel\n1. Add to {PRINT_IDIOM_DECK if data["is_chengyu"] else PRINT_WORD_DECK}\n2. Switch Deck\n3. Edit English meaning\n4. Regenerate example sentence\n5. Type in example sentence manually\n6. Type in notes"
            print(f"""0. Cancel
1. Add to {PRINT_IDIOM_DECK if data["is_chengyu"] else PRINT_WORD_DECK}
2. Switch Deck
3. Edit English meaning
(Type 'm' for full menu)""")
        else:
            display_menu = True
        user_input = input("> ").strip().lower()
        if user_input == "0" or user_input == "exit" or user_input == "cancel":
            return
        elif user_input == "1" or user_input == "add":
            add_to_anki(vocab_word, data)
            return
        elif user_input == "2" or user_input == "swap" or user_input == "switch":
            data["is_chengyu"] = not data["is_chengyu"]
        elif user_input == "3":
            data["meaning_english"] = replace_except_on_escape(data["meaning_english"], "Type in new meaning: ")
        elif user_input == "4":
            data["part_of_speech_english"] = replace_except_on_escape(data["part_of_speech_english"], "Type in new part of speech: ")
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
            data["sentencemeaning_english"] = new_example["sentencemeaning_english"]
        elif user_input == "6" or user_input == "generate" or user_input == "regenerate" or user_input == "gen" or user_input == "regen":
            new_sentence = input("Type in new example sentence: ").strip()
            if new_sentence.lower() == "/q":
                continue
            print("(Note: you can type /t for a machine translation)")
            english_translation = input("Type in the English translation: ").strip()
            if english_translation.lower() == "/t":
                response = chat(
                    model='qwen3.5:4b',
                    messages=[
                        {
                            'role': 'system',
                            'content': 'Translate this sentence to English. Do not return anything else.',
                        },
                        {
                            'role': 'user',
                            'content': new_sentence,

                        },
                    ],
                    options={'temperature': 0},  # Low temperature ensures strict format adherence
                    think=False,  # turn off extended reasoning
                )
                data["sentencemeaning_english"] = response.message.content
            elif english_translation.lower() == "/q":
                continue
            else:
                data["sentencemeaning_english"] = english_translation
            data["sentencesimplified"] = new_sentence
        elif user_input == "7" or user_input == "notes" or user_input == "note":
            data["notes"] = replace_except_on_escape(data["notes"], "Type in notes: ")
        elif user_input == "8" or user_input == "pinyin":
            print(f"Word: {vocab_word}")
            print(to_pinyin(vocab_word))
            print(f"Example Sentence: {data["sentencesimplified"]}")
            print(to_pinyin(data["sentencesimplified"]))
            display_menu = False
        elif user_input == "m" or user_input == "menu":
            print(f"""4. Edit part of speech
5. Generate new example sentence
6. Type in example sentence manually
7. Type in notes
8. Show pinyin""")
            display_menu = False
        else:
            print(f"'{user_input}' is not a valid command. Please look at the menu for help.")
            display_menu = False


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
        cedict = CcCedict()
        for i in range(1, len(sys.argv)):
            if len(sys.argv) > 2:
                print(f"====={i} of {len(sys.argv) - 1}=====")
            if is_chinese(sys.argv[i]):
                generate_card(sys.argv[i])
            else:
                print(f'"{sys.argv[i]}" is not Mandarin Chinese. Skipping...')
    else:
        print("Which word do you want to add into Anki?")
