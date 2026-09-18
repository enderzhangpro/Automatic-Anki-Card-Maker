#!/usr/bin/env python3

from collections import Counter
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
CHINESE_TO_ENGLISH = "CH → EN"
ENGLISH_TO_CHINESE = "EN → CH"
ENGLISH_TO_CHINESE_CLOZE = "EN → CH (cloze)"
CYAN = '\033[36m'
GREEN = '\033[32m'
# YELLOW = '\033[33m'
# MAGENTA = '\033[35m'
# BRIGHT_RED = '\033[91m'
RED = '\033[31m'
BOLD = '\033[1m'
RESET = '\033[0m'


class Deck:

    def __init__(self, name, note_type, color):
        self.name = name
        self.note_type = note_type
        self.color = color

    def __str__(self):
        return f"{BOLD}{self.color}{self.name}{RESET}"


PRODUCTION_DECK = Deck("Production", ENGLISH_TO_CHINESE_CLOZE, CYAN)
IDIOM_DECK = Deck("Idioms & Set Phrases", ENGLISH_TO_CHINESE_CLOZE, RED)
RECOGNITION_DECK = Deck("Recognition", CHINESE_TO_ENGLISH, GREEN)


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


def print_warning(text, text_color=RED, bolded=False):
    if not bolded:
        print(f"{text_color}{text}{RESET}")
    else:
        print(f"{text_color}{BOLD}{text}{RESET}")


def invoke(action, **params):
    payload = {"action": action, "version": 6, "params": params}
    resp = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
    result = resp.json()
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result["result"]


def has_exact_quantities(sub_str, target_str):
    c1 = Counter(sub_str)
    c2 = Counter(target_str)
    # Check if every character count in sub_str is less than or equal to target_str
    return all(c2[char] >= count for char, count in c1.items())


def make_cloze_sentence(sentence, vocab_word):
    if not has_exact_quantities(vocab_word, sentence):
        return None
    output_sentence = ""
    i = 0
    j = sentence.index(vocab_word[0])

    while True:
        output_sentence += sentence[i:j] + "[ ]"
        k = j + len(vocab_word)
        slice_to_test = sentence[j:k]
        while not has_exact_quantities(vocab_word, sentence[j:k]) and k < len(sentence):
            k += 1
        i = k
        j = sentence.find(vocab_word[0], i)
        if j == -1:
            return output_sentence + sentence[i:]


def call_cloze(sentence, vocab_word, suppress_print=False):
    output = make_cloze_sentence(sentence, vocab_word)
    if output is not None:
        return output
    if not suppress_print:
        print_warning(f"Error: '{vocab_word}' not found in its entirely in AI-generated example sentence.")
    return sentence


def add_to_anki(word, data, target_deck):
    note = {
        "deckName": target_deck.name,
        "modelName": target_deck.note_type,
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
            "SentenceSimplifiedCloze": data["sentencesimplifiedcloze"],
            "SentenceTraditionalCloze": "",
            "SentencePinyin.1": to_pinyin(data["sentencesimplified"]),
            "SentencePinyin.2": "",
            "SentenceMeaning": data["sentencemeaning_english"],
            "SentenceAudio": "",
            "SentenceImage": "",
            "Notes": data["notes"],
        },
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
        "tags": ["recognition"] if target_deck == RECOGNITION_DECK else [],
    }
    try:
        note_id = invoke("addNote", note=note)
    except requests.exceptions.ConnectionError:
        print("Error: Anki is closed.")
        sys.exit(0)
    except RuntimeError:
        print(f'"{word}" already exists in {target_deck} — skipped.')
        return
    print(f"Added '{word}' as note {note_id} to {target_deck}.")
    return note_id


class ExtraNoteWithoutVocabTranslation(BaseModel):
    is_chengyu: bool = Field(description="True if this vocabulary word is an idiom or four character phrase, false otherwise")
    is_literary: bool = Field(description="True if this word is primarily encountered in written Chinese (news, literature, formal writing) and would rarely be spoken aloud in everyday conversation, false if it is common in everyday spoken Mandarin")
    part_of_speech_english: str = Field(description="The part(s) of speech of this word in English")
    sentencesimplified: str = Field(description="An example sentence including the word in simplified Mandarin")
    sentencemeaning_english: str = Field(description="The English translation of the example sentence")


class ExtraNote(BaseModel):
    is_chengyu: bool = Field(description="True if this vocabulary word is an idiom or four character phrase, false otherwise")
    is_literary: bool = Field(description="True if this word is primarily encountered in written Chinese (news, literature, formal writing) and would rarely be spoken aloud in everyday conversation, false if it is common in everyday spoken Mandarin")
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
                    f'(2) whether this word is primarily encountered in written/literary Chinese rather than spoken aloud in everyday conversation, '
                    f'(3) part of speech — written in English, '
                    f'(4) an example sentence in simplified Chinese, '
                    f'(5) the English translation of that example sentence.',
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
        # to get rid of the annoying measure word entries
        cleared_definitions = [d for d in dictionary_entry['definitions'] if not d.startswith("CL:")]
        for i in range(len(cleared_definitions)):
            data["meaning_english"] += cleared_definitions[i]
            if i < len(cleared_definitions) - 1:
                data["meaning_english"] += "; "
    else:
        print_warning(f"Warning: '{vocab_word}' not found in Chinese-English CC-CEDICT dictionary. Reverting to LLM definition...")
        response = chat(
            model='qwen3.5:4b',
            messages=[
                {
                    'role': 'user',
                    'content': f'For the Mandarin word "{vocab_word}", provide: '
                    f'(1) whether this is a chengyu, '
                    f'(2) whether this word is primarily encountered in written/literary Chinese rather than spoken aloud in everyday conversation, '
                    f'(3) meaning — written in English, '
                    f'(4) part of speech — written in English, '
                    f'(5) an example sentence in simplified Chinese, '
                    f'(6) the English translation of that example sentence.',
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
    data["original_is_literary"] = data["is_literary"]
    data["sentencesimplifiedcloze"] = call_cloze(data["sentencesimplified"], vocab_word)
    display_menu = True

    def replace_except_on_escape(original_value, prompt):
        user_input = input(prompt).strip()
        if user_input.lower() != "/q":
            return user_input
        return original_value

    if data["is_chengyu"]:
        target_deck = IDIOM_DECK
    elif data["is_literary"]:
        target_deck = RECOGNITION_DECK
    else:
        target_deck = PRODUCTION_DECK

    decks = [PRODUCTION_DECK, RECOGNITION_DECK, IDIOM_DECK]
    shorthand = {PRODUCTION_DECK.name: ["production", "prod"],
                 RECOGNITION_DECK.name: ["recognition", "recog"],
                 IDIOM_DECK.name: ["idioms", "idiom", "phrases", "phrase"]}

    while True:
        if display_menu:
            print(f"Deck: {target_deck}")
            print(f"Word: {vocab_word}")
            print(f"Meaning: {data["meaning_english"]}")
            print(f"Part of Speech: {data["part_of_speech_english"]}")
            print(f"Example Sentence: {data["sentencesimplified"]}")
            print(f"Cloze Example Sentence: ", end="")
            if '[ ]' not in data["sentencesimplifiedcloze"]:
                print_warning(data["sentencesimplifiedcloze"], bolded=True)
            else:
                print(data["sentencesimplifiedcloze"])
            print(f"Sentence Meaning: {data["sentencemeaning_english"]}")
            if data["notes"] != "":
                print(f"Notes: {data["notes"]}")
            print(f"0. Cancel\n1. Add to {target_deck}")
            counter = 2
            options = []
            for deck in decks:
                if deck == target_deck:
                    continue
                print(f"{counter}. Switch to {deck.name}")
                options.append(deck)
                counter += 1
            print("(Type 'm' for full menu)")
        else:
            display_menu = True
        user_input = input("> ").strip().lower()
        if user_input == "0" or user_input == "exit" or user_input == "cancel":
            return
        elif user_input == "1" or user_input == "add":
            add_to_anki(vocab_word, data, target_deck)
            return
        elif user_input == "2" or user_input in shorthand[options[0].name]:
            target_deck = options[0]
        elif user_input == "3" or user_input in shorthand[options[1].name]:
            target_deck = options[1]
        elif user_input == "4" or user_input == "define" or user_input == "meaning":
            data["meaning_english"] = replace_except_on_escape(data["meaning_english"], "Type in new meaning: ")
        elif user_input == "5":
            data["part_of_speech_english"] = replace_except_on_escape(data["part_of_speech_english"], "Type in new part of speech: ")
        elif user_input == "6" or user_input == "generate" or user_input == "regenerate" or user_input == "gen" or user_input == "regen":
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
            data["sentencesimplifiedcloze"] = call_cloze(data["sentencesimplified"], vocab_word)
            data["sentencemeaning_english"] = new_example["sentencemeaning_english"]
        elif user_input == "7" or user_input == "manual":
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
                    options={'temperature': 0},
                    think=False,
                )
                data["sentencemeaning_english"] = response.message.content
            elif english_translation.lower() == "/q":
                continue
            else:
                data["sentencemeaning_english"] = english_translation
            data["sentencesimplifiedcloze"] = call_cloze(new_sentence, vocab_word)
            data["sentencesimplified"] = new_sentence
        elif user_input == "8" or user_input == "notes" or user_input == "note":
            data["notes"] = replace_except_on_escape(data["notes"], "Type in notes: ")
        elif user_input == "9" or user_input == "pinyin":
            print(f"Word: {vocab_word}")
            print(to_pinyin(vocab_word))
            print(f"Example Sentence: {data["sentencesimplified"]}")
            print(to_pinyin(data["sentencesimplified"]))
            display_menu = False
        elif user_input == "10" or user_input == "cloze":
            print("Note: replace cloze sections with '[ ]'")
            data["sentencesimplifiedcloze"] = replace_except_on_escape(data["sentencesimplifiedcloze"], "Type in new cloze sentence: ")
            if '[ ]' not in data["sentencesimplifiedcloze"]:
                print_warning(f"Warning: your submitted sentence does not contain any cloze deletions.")
        elif user_input == "m" or user_input == "menu":
            print(f"""4. Edit English meaning
5. Edit part of speech
6. Generate new example sentence
7. Type in example sentence manually
8. Type in notes
9. Show pinyin
10. Type in cloze sentence""")
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
        cedict = CcCedict()  # must initialize dictionary before use
        for i in range(1, len(sys.argv)):
            if len(sys.argv) > 2:
                print(f"====={i} of {len(sys.argv) - 1}=====")
            if is_chinese(sys.argv[i]):
                generate_card(sys.argv[i])
            else:
                print(f'"{sys.argv[i]}" is not Mandarin Chinese. Skipping...')
    else:
        print("Which word do you want to add into Anki?")
