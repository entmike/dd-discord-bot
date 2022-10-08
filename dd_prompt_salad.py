import random, re
from pydotted import pydot
from loguru import logger

# Idea Credit: aztec_man#3032 and https://colab.research.google.com/drive/1O4gyR8XBNeTHhOlwQZx_S4eCwxtqdbWi
def make_random_prompt(template="{colors} {things} in the {custom/customword} shape of {shapes}, art by {artists}", amount=5, prompt_salad_path="prompt_salad"):
    promptList = []
    for i in range(amount):

        prompt_dict = {}
        tokens = re.findall(r"\{(.*?)\}", template)
        # files to import
        for token in tokens:
            try:
                prompt_dict[token] = open(f"{prompt_salad_path}/{token}.txt").read().splitlines()
            except:
                prompt_dict[token] = None
                logger.warning(f"⚠️ Token {token} not found in prompt salad folder.")

        # Thanks, Zippy#1111 for your regex lambda wizardry
        regex = re.compile(r"\{(.*?)\}", re.A | re.I | re.M)
        matcher = lambda x, d: re.subn(
            regex,
            lambda m: random.choice(d[x[m.start() + 1 : m.end() - 1]]) if d[x[m.start() + 1 : m.end() - 1]] else x[m.start() + 1 : m.end() - 1],
            x,
            re.I | re.M | re.A | re.M,
        )[0]
        promptList.append(matcher(template, prompt_dict))
    # logger.debug(promptList)
    return promptList


def main():
    promptList = make_random_prompt(amount=5)
    print(promptList)
    for k in promptList:
        pass
        # print(k)


if __name__ == "__main__":
    main()
