import datetime
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

from db import get_database

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
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        query = {"status": "complete"}
        completed = queueCollection.count_documents(query)
        if completed == 0:
            # print("No new events.")
            return
        else:
            completedJob = queueCollection.find_one(query)
            channel = discord.utils.get(bot.get_all_channels(), name="general")
            embed = discord.Embed(
                title=f"Job {completedJob.get('uuid')}",
                description=completedJob.get("text_prompt"),
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
            file = discord.File(f"images/{completedJob.get('filename')}", filename=completedJob.get("filename"))
            embed.set_image(url=f"attachment://{completedJob.get('filename')}")
            results = queueCollection.update_one({"uuid": completedJob.get("uuid")}, {"$set": {"status": "archived"}})
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
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        query = {"author": str(ctx.author)}
        jobCount = queueCollection.count_documents(query)
        if jobCount >= AUTHOR_LIMIT:
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
        with get_database() as client:
            job_uuid = str(uuid.uuid4())
            record = {"uuid": job_uuid, "text_prompt": text_prompt, "steps": steps, "author": str(ctx.author), "status": "queued", "timestamp": datetime.datetime.utcnow()}
            queueCollection = client.database.get_collection("queue")
            queueCollection.insert_one(record)
            await ctx.respond(f"✅ Request added to DB")

    else:
        await ctx.respond("\n".join(reasons))


@bot.command()
async def remove(ctx, uuid):
    author = str(ctx.author)
    with get_database() as client:
        result = client.database.get_collection("queue").delete_many({"author": author, "uuid": uuid})
        count = result.deleted_count

        if count == 0:
            await ctx.respond(f"❌ Could not delete job `{uuid}`.  Check the Job ID and if you are the owner.")
        else:
            await ctx.respond(f"🗑️ Job removed.")


@bot.command()
async def queue(ctx):
    with get_database() as client:
        queue = client.database.get_collection("queue").find({"$query": {"status": {"$ne": "archived"}}, "$orderby": {"timestamp": -1}})
        # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
        embed = discord.Embed(
            title="Request Queue",
            description="The following requests are queued up.",
            color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
        )
        for j, job in enumerate(queue):
            summary = f"""
            - 🧑‍🦲 Author: `{job.get('author')}`
            - ✍️ Text Prompt: `{job.get('text_prompt')}`
            - Status: `{job.get('status')}`
            - Timestamp: `{job.get('timestamp')}`
            - Agent: `{job.get('agent_id')}`
            """
            embed.add_field(name=job.get("uuid"), value=summary, inline=False)
    await ctx.respond(embed=embed)


@bot.command()
async def agents(ctx):
    # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
    embed = discord.Embed(
        title="Agent Status",
        description="The following agents are registered.",
        color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
    )

    with get_database() as client:
        agents = client.database.get_collection("agents").find()

        for a, agent in enumerate(agents):
            embed.add_field(name=agent.get("agent_id"), value=f"- {agent.get('gpu')}", inline=False)
        await ctx.respond(embed=embed)


if __name__ == "__main__":
    print(discord.__version__)
    from discord.ext import tasks, commands

    bot.run(os.getenv("DISCORD_TOKEN"))
