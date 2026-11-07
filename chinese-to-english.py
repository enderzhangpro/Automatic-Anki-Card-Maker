#!/usr/bin/env python3

from pycccedict.cccedict import CcCedict
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cedict = CcCedict()
        for i in range(len(sys.argv[1:])):
            word = sys.argv[1:][i]
            dictionary_entry = cedict.get_entry(word)
            if dictionary_entry is not None:
                print(f"Simplified: {dictionary_entry['simplified']}")
                print(f"Traditional: {dictionary_entry['traditional']}")
                print(f"Pinyin: {dictionary_entry['pinyin']}")
                print(f"Definitions: ", end="")
                cleared_definitions = [d for d in dictionary_entry['definitions'] if not d.startswith("CL:")]
                for i in range(len(cleared_definitions)):
                    print(cleared_definitions[i], end="")
                    if i < len(cleared_definitions) - 1:
                        print("; ", end="")
                print()
                if i < len(sys.argv[1:]):
                    print()
            else:
                print(f"'{word}' is not Mandarin Chinese. Skipping...")
    else:
        print("Which Chinese word do you want me to define?")
