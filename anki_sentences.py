#!/usr/bin/env python3

import json
from ollama import chat
from pydantic import BaseModel, Field
import os
from pypinyin import pinyin
import re
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
SENTENCE_DECK = "Substitution Drills"
NOTE_TYPE = "Chinese Cloze Sentence+"


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


def add_to_anki(cloze_sentence, substitutions, continuation_sentences, model_name=NOTE_TYPE):

    def to_html(text):
        return text.replace("\n", "<br>") if text else text

    note = {
        "deckName": SENTENCE_DECK,
        "modelName": model_name,
        "fields": {
            "Text": cloze_sentence,
            "Related Words": to_html(substitutions),
            "Examples": to_html(continuation_sentences),
            "Back Extra": ""
        },
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    }
    try:
        note_id = invoke("addNote", note=note)
    except requests.exceptions.ConnectionError:
        print("Error: Anki is closed.")
        sys.exit(0)
    except RuntimeError:
        print(f'"{cloze_sentence}" already exists in {SENTENCE_DECK} — skipped.')
        return
    print(f"Added '{cloze_sentence}' as note {note_id} to {SENTENCE_DECK}.")
    return note_id


class Substitutions(BaseModel):
    additional_substitutions: str = Field(
        description="Comma-separated Chinese words only, e.g. 一，二，三. No explanations, no English, no pinyin."
    )


class ContinuationSentences(BaseModel):
    continuation_sentences: list[str] = Field(
        description="Three short, simple continuation sentences written entirely in Chinese characters."
    )


def build_cloze(raw_sentence: str) -> tuple[str, str, list[str]]:
    """Given a sentence with {word} marking the blank, return (plain_sentence, cloze_sentence)."""
    parts = re.split(r"\{|\}|\[|\]", raw_sentence)
    plain = "".join(parts)
    cloze = "".join(
        part if i % 2 == 0 else f"{{{{c1::{part}}}}}"
        for i, part in enumerate(parts)
    )
    return plain, cloze


def build_blanks(raw_sentence: str) -> list[str]:
    parts = re.split(r"\{|\}|\[|\]", raw_sentence)
    blanks = []
    answers = []

    for i in range(len(parts)):
        if i % 2 == 0:
            continue
        sentence = ""
        for j in range(len(parts)):
            if i == j:
                answers.append(parts[j])
                for k in parts[j]:
                    sentence += "_"
            else:
                sentence += parts[j]
        blanks.append(sentence)
    return blanks, answers


def generate_card(raw_sentence):
    plain_sentence, cloze_sentence = build_cloze(raw_sentence)
    blanks, answers = build_blanks(raw_sentence)
    if len(answers) == 0:
        print("No cloze deletion chunks.")
        return
    substitutions = []
    for i in range(len(blanks)):
        response = chat(
            model='qwen3.5:4b',
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'You are a Mandarin Chinese teaching assistant generating Anki substitution-drill notes. '
                        'Respond only in the requested JSON schema, with no extra commentary. '
                        'additional_substitutions must be ONLY a comma-separated list of Chinese words '
                        '(e.g. 一，二，三) — no explanations, no pinyin, no English. '
                    ),
                },
                {
                    'role': 'user',
                    'content': (
                        f'The sentence is: {blanks[i]}\n'
                        f'The blank to substitute is marked in underscores\n\n'
                        f'Provide 3-5 additional word substitutions that could naturally fill the same blank, except for {answers[i]}'
                    ),
                },
            ],
            options={'temperature': 0},
            think=False,
        )
        raw_content = response.message.content
        data = json.loads(raw_content)
        substitutions.append(data["additional_substitutions"])

    response = chat(
        model='qwen3.5:4b',
        messages=[
            {
                'role': 'system',
                'content': (
                        'You are a Mandarin Chinese teaching assistant generating Anki substitution-drill notes. '
                        'Respond only in the requested JSON schema, with no extra commentary. '
                        'continuation_sentences must be three short, simple sentences written entirely in '
                        'Chinese characters, with no English and no curly braces.'
                ),
            },
            {
                'role': 'user',
                'content': (
                        f'The sentence is: {plain_sentence}\n'
                        f'The blank to substitute is marked in underscores\n\n'
                        f'Provide three continuation sentences in Chinese that a learner could use to practice '
                        f'improvising after this sentence.'
                ),
            },
        ],
        format=ContinuationSentences.model_json_schema(),
        options={'temperature': 0},
        think=False,
    )
    raw_content = response.message.content
    data = json.loads(raw_content)
    sub_list = ""
    for i in range(len(substitutions)):
        sub_list += f"{i + 1}. {substitutions[i]}"
        if i < len(substitutions) - 1:
            sub_list += "\n"
    con_list = ""
    for i in range(len(data['continuation_sentences'])):
        con_list += f"{i + 1}. {data['continuation_sentences'][i]}"
        if i < len(data['continuation_sentences']) - 1:
            con_list += "\n"

    while True:
        print(f"Cloze Sentence: {cloze_sentence}")
        print("Substitutions:")
        print(sub_list)
        print("Continuations:")
        print(con_list)
        menu = f"\n0. Cancel\n1. Add to {SENTENCE_DECK}"
        print(menu)
        user_input = input("> ").strip()
        if user_input == "0":
            return
        elif user_input == "1":
            add_to_anki(cloze_sentence, sub_list, con_list)
            return


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
        raw_sentence = " ".join(sys.argv[1:])
        generate_card(raw_sentence)
    else:
        print("Which sentence do you want me to cloze?")
