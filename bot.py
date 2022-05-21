import discord, os, subprocess
from discord.ext import tasks
from dotenv import load_dotenv
from numpy import full
from pydotted import pydot
from loguru import logger
import time
from yaml import dump, full_load
import uuid

import warnings

warnings.filterwarnings("ignore")
from profanity_check import predict_prob

load_dotenv()

agents = ["mike"]
ticks = 0

# this code will be executed every 10 seconds after the bot is ready
@tasks.loop(seconds=10)
async def task_loop():
    global ticks
    ticks += 1
    with open("queue.yaml", "r") as queue:
        arr = full_load(queue)

    for job in arr:
        if job["status"] == "complete":
            channel = discord.utils.get(bot.get_all_channels(), name="general")
            embed = discord.Embed(
                title=f"Job {job['uuid']}",
                description=job["text_prompt"],
                color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
            )
            embed.set_author(
                name="Fever Dream",
                icon_url="https://cdn.howles.cloud/icon.png",
            )

            view = discord.ui.View()

            async def loveCallback(interaction):
                await interaction.response.edit_message(content="💖", view=view)

            async def hateCallback(interaction):
                await interaction.response.edit_message(content="😢", view=view)

            loveButton = discord.ui.Button(label="Love it", style=discord.ButtonStyle.green, emoji="😍")
            loveButton.callback = loveCallback
            hateButton = discord.ui.Button(label="Hate it", style=discord.ButtonStyle.danger, emoji="😢")
            hateButton.callback = hateCallback
            view.add_item(loveButton)
            view.add_item(hateButton)
            file = discord.File(f"images/{job['filename']}", filename=job["filename"])
            embed.set_image(url=f"attachment://{job['filename']}")

            await channel.send("Completed render", embed=embed, view=view, file=file)

    # agents = open("agents.txt","r").read()
    # if agents != oldagents:
    #   await channel.send("New render agent found.")

    # oldagents = agents
    print(ticks)
    # await channel.send("tick")


bot = discord.Bot(debug_guilds=[945459234194219029])  # specify the guild IDs in debug_guilds
arr = []
agents = []
STEP_LIMIT = int(os.getenv("STEP_LIMIT", 150))
PROFANITY_THRESHOLD = float(os.getenv("PROFANITY_THRESHOLD", 0.7))
AUTHOR_LIMIT = int(os.getenv("AUTHOR_LIMIT", 2))


@bot.command(description="Sends the bot's latency.")  # this decorator makes a slash command
async def ping(ctx):  # a slash command will be created with the name "ping"
    await ctx.respond(f"Pong! Latency is {bot.latency}")


@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")
    task_loop.start()  # important to start the loop


@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server, {member.mention}! Enjoy your stay here.")


@bot.command()
async def gtn(ctx):
    """A Slash Command to play a Guess-the-Number game."""
    play = True
    while play:
        await ctx.respond("Guess a number between 1 and 10.  -1 to give up.")
        guess = await bot.wait_for("message", check=lambda message: message.author == ctx.author)

        if int(guess.content) == -1:
            await ctx.send("All good.  Maybe you'll win next time...")
            play = False
            return
        if int(guess.content) == 5:
            await ctx.send("You guessed it!")
            play = False
        else:
            await ctx.send("Nope, try again.")


@bot.command()
async def render(
    ctx,
    text_prompt: discord.Option(str, "Enter your text prompt", required=False, default="lighthouses on artstation"),
    steps: discord.Option(int, "Number of steps", required=False, default=150),
):
    reject = False
    reasons = []
    authorCount = 0
    try:
        with open("queue.yaml", "r") as queue:
            arr = full_load(queue)
    except:
        print("Empty queue file found.  Initializing...")
        arr = []

    for job in arr:
        job = pydot(job)
        if job.author == str(ctx.author):
            authorCount += 1
    if authorCount >= AUTHOR_LIMIT:
        reject = True
        reasons.append(f"- ❌ You have too many jobs queued.  Wait until your queued job count is under {AUTHOR_LIMIT} or remove an existing with /remove command.")
    if steps > STEP_LIMIT:
        reject = True
        reasons.append(f"- ❌ Too many steps.  Limit your steps to {STEP_LIMIT}")
    profanity = predict_prob([text_prompt])[0]
    if profanity >= PROFANITY_THRESHOLD:
        reject = True
        reasons.append(f"- ❌ Profanity detected.  Watch your fucking mouth.")
    if not reject:
        job_uuid = str(uuid.uuid4())
        arr.append({"uuid": job_uuid, "text_prompt": text_prompt, "steps": steps, "author": str(ctx.author), "status": "queued"})
        dump(arr, open("queue.yaml", "w"))
        await ctx.respond(f"✅ Request added to list")
    else:
        await ctx.respond("\n".join(reasons))


# @bot.command()
# async def cmd(ctx, command: discord.Option(str, "Enter your command", required=False, default="ls -lart")):
#     arr.append(command)
#     res = subprocess.run(command.split(" "), stdout=subprocess.PIPE).stdout.decode("utf-8")
#     await ctx.respond(f"```\n{res}\n```")
@bot.command()
async def remove(ctx, uuid):
    author = str(ctx.author)
    with open("queue.yaml", "r") as queue:
        arr = full_load(queue)
    for j, job in enumerate(arr):
        if job["uuid"] == uuid:
            if job["author"] == author:
                del arr[j]
                dump(arr, open("queue.yaml", "w"))
                await ctx.respond(f"🗑️ Job removed.")
            else:
                await ctx.respond(f"❌ You are not {job['author']}!")
    await ctx.respond(f"❌ Job not found.")


@bot.command()
async def queue(ctx):
    try:
        with open("queue.yaml", "r") as queue:
            arr = full_load(queue)
    except:
        print("Empty queue file found.  Initializing...")
        arr = []
    # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
    embed = discord.Embed(
        title="Request Queue",
        description="The following requests are queued up.",
        color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
    )
    for j, job in enumerate(arr):
        job = pydot(job)
        summary = f"- Author: `{job.author}`\n - Text Prompt: `{job.text_prompt}`\n - Status: {job.status}"
        embed.add_field(name=job.uuid, value=summary, inline=False)
    await ctx.respond(embed=embed)


@bot.command()
async def agents(ctx):
    # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
    embed = discord.Embed(
        title="Agent Status",
        description="The following agents are running",
        color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
    )
    with open("agents.yaml", "r") as queue:
        arr = full_load(queue)

    for a, agent in enumerate(arr):
        embed.add_field(name=agent["agent_id"], value=f"- {agent['gpu']}", inline=False)
    await ctx.respond(embed=embed)


@bot.command()
async def test(ctx):
    # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
    embed = discord.Embed(
        title="Job #0",
        description="Some Text Prompts here?",
        color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
    )

    # embed.add_field(name="A Normal Field", value="A really nice field with some information. **The description as well as the fields support markdown!**")

    # embed.add_field(name="Inline Field 1", value="Inline Field 1", inline=True)
    # embed.add_field(name="Inline Field 2", value="Inline Field 2", inline=True)
    # embed.add_field(name="Inline Field 3", value="Inline Field 3", inline=True)

    # embed.set_footer(text="Footer! No markdown here.")  # footers can have icons too
    embed.set_author(
        name="Fever Dream",
        icon_url="https://cdn.howles.cloud/icon.png",
    )

    view = discord.ui.View()

    async def loveCallback(interaction):
        await interaction.response.edit_message(content="💖", view=view)

    async def hateCallback(interaction):
        await interaction.response.edit_message(content="😢", view=view)

    loveButton = discord.ui.Button(label="Love it", style=discord.ButtonStyle.green, emoji="😍")
    loveButton.callback = loveCallback
    hateButton = discord.ui.Button(label="Hate it", style=discord.ButtonStyle.danger, emoji="😢")
    hateButton.callback = hateCallback
    view.add_item(loveButton)
    view.add_item(hateButton)
    file = discord.File("prevFrame.png", filename="image.png")
    embed.set_image(url="attachment://image.png")

    # ar = discord.ActionRow([discord.ui.button(label="Love it", style=discord.ButtonStyle.primary)])
    # embed.append_field(ar)
    # embed.set_thumbnail(url="https://example.com/link-to-my-thumbnail.png")
    # embed.set_image(url="https://example.com/link-to-my-banner.png")

    await ctx.respond(embed=embed, file=file, view=view)  # Send the embed with some text


# class View(discord.ui.View):  # Create a class called View that subclasses discord.ui.View
#     @discord.ui.button(label="Love it", style=discord.ButtonStyle.primary)  # Create a button with the label "😎 Click me!" with color Blurple
#     @discord.ui.button(label="Hate it", style=discord.ButtonStyle.primary)  # Create a button with the label "😎 Click me!" with color Blurple
#     async def button_callback(self, button, interaction):
#         await interaction.response.send_message("You clicked the button!")  # Send a message when the button is clicked


@bot.slash_command()  # Create a slash command
async def button(ctx):
    # f = open('prevFrame.png','rb')
    # data = f.read()
    await ctx.respond("Test Image", file=discord.File(open("prevFrame.png", "rb"), filename="prevFrame.png"))


if __name__ == "__main__":
    print(discord.__version__)
    from discord.ext import tasks, commands

    bot.run(os.getenv("DISCORD_TOKEN"))
