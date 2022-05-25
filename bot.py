import datetime
from random import choices
import discord, os, subprocess
from discord.ext import tasks
from dotenv import load_dotenv
from numpy import full
from pydotted import pydot
from loguru import logger
import time
from yaml import dump, full_load
import uuid
from bson import Binary, Code
from bson.json_util import dumps
import warnings
import json

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
    image_channels = ["images", "general"]
    botspam_channels = ["botspam"]
    with get_database() as client:
        messageCollection = client.database.get_collection("logs")
        messages = messageCollection.find({"$query": {"ack": {"$ne": True}}})
        for message in messages:
            title = "Message"
            if message.get("title"):
                title = message.get(title)
            embed = discord.Embed(
                title=title,
                description=message.get("message"),
                color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
            )
            for channel in botspam_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                await channel.send(embed=embed)
                messageCollection.update_one({"uuid": message.get("uuid")}, {"$set": {"ack": True}})
        
        
        
        query = {"status": "complete"}
        queueCollection = client.database.get_collection("queue")
        completed = queueCollection.count_documents(query)
        if completed == 0:
            # print("No new events.")
            return
        else:
            completedJob = queueCollection.find_one(query)
            for channel in image_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
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

                # loveButton = discord.ui.Button(label="Love it", style=discord.ButtonStyle.green, emoji="😍")
                # loveButton.callback = loveCallback
                # hateButton = discord.ui.Button(label="Hate it", style=discord.ButtonStyle.danger, emoji="😢")
                # hateButton.callback = hateCallback
                # view.add_item(loveButton)
                # view.add_item(hateButton)
                file = discord.File(f"images/{completedJob.get('filename')}", filename=completedJob.get("filename"))
                embed.set_image(url=f"attachment://{completedJob.get('filename')}")
                results = queueCollection.update_one({"uuid": completedJob.get("uuid")}, {"$set": {"status": "archived"}})
                await channel.send(f"Completed render <@{completedJob.get('author')}>", embed=embed, view=view, file=file)


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


@bot.command(description="Submit a Disco Diffusion Render Request")
async def render(
    ctx,
    text_prompt: discord.Option(str, "Enter your text prompt", required=False, default="lighthouses on artstation"),
    steps: discord.Option(int, "Number of steps", required=False, default=150),
    shape: discord.Option(str, "Image Shape", required=False, default="landscape", choices=[
        discord.OptionChoice("Landscape", value="landscape"),
        discord.OptionChoice("Portrait", value="portrait"),
        discord.OptionChoice("Square", value="square"),
        discord.OptionChoice("Panoramic", value="pano")
    ]),
    model: discord.Option(str, "Models", required=False, default="default", choices=[
        discord.OptionChoice("Default (ViTL16+32, RN50)", value="default"),
        discord.OptionChoice("ViTL16+32, RN50x64", value="rn50x64"),
        discord.OptionChoice("ViTL16+32+14", value="vitl14"),
        discord.OptionChoice("ViTL16+32+14x336", value="vitl14x336"),
    ]),
    clip_guidance_scale: discord.Option(int, "CLIP guidance scale", required=False, default=1500),
    cut_ic_pow: discord.Option(int, "CLIP Innercut Power", required=False, default=1),
):
    reject = False
    reasons = []
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        query = {"author": int(ctx.author.id), "status": {"$ne": "archived"}}
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
            text_prompt = text_prompt.replace(':','')
            record = {
                "uuid": job_uuid, 
                "text_prompt": text_prompt, 
                "steps": steps, 
                "shape": shape, 
                "model": model,
                "clip_guidance_scale": clip_guidance_scale,
                "cut_ic_pow": cut_ic_pow,
                "author": int(ctx.author.id),
                "status": "queued",
                "timestamp": datetime.datetime.utcnow()}
            queueCollection = client.database.get_collection("queue")
            queueCollection.insert_one(record)
            await ctx.respond(f"✅ Request added to DB")

    else:
        await ctx.respond("\n".join(reasons))


@bot.command(description="Nuke Render Queue (debug)")
async def nuke(ctx):
    with get_database() as client:
        result = client.database.get_collection("queue").delete_many({"status": {"$ne": "archived"}})
    await ctx.respond(f"✅ Queue nuked.")


@bot.command(description="Remove a render request (intended for admins)")
async def destroy(ctx, uuid):
    with get_database() as client:
        result = client.database.get_collection("queue").delete_many({"uuid": uuid})
        count = result.deleted_count

        if count == 0:
            await ctx.respond(f"❌ Could not delete job `{uuid}`.  Check the Job ID.")
        else:
            await ctx.respond(f"🗑️ Job destroyed.")

@bot.command(description="Remove a render request")
async def remove(ctx, uuid):
    with get_database() as client:
        result = client.database.get_collection("queue").delete_many({"author": int(ctx.author.id), "uuid": uuid, "status": "queued"})
        count = result.deleted_count

        if count == 0:
            await ctx.respond(f"❌ Could not delete job `{uuid}`.  Check the Job ID and if you are the owner, and that your job has not started running yet.")
        else:
            await ctx.respond(f"🗑️ Job removed.")

@bot.command(description="Retry a render request")
async def retry(ctx, uuid):
    with get_database() as client:
        result = client.database.get_collection("queue").update_one({"uuid": uuid, "author": int(ctx.author.id)}, {"$set": {"status": "queued"}})
        count = result.modified_count

        if count == 0:
            await ctx.respond(f"❌ Cannot retry {uuid}")
        else:
            await ctx.respond(f"💼 Job marked for retry.")

@bot.command(description="Repeat a render request")
async def repeat(ctx, job_uuid):
    with get_database() as client:
        result = client.database.get_collection("queue").find_one({"uuid": job_uuid}, {'_id': 0})
        new_uuid = str(uuid.uuid4())
        result["uuid"] = new_uuid
        result["status"] = 'queued'
        result["author"] = int(ctx.author.id)
        result = client.database.get_collection("queue").insert_one(result)
        insertID = result

        if not insertID:
            await ctx.respond(f"❌ Cannot repeat {uuid}")
        else:
            await ctx.respond(f"💼 Job marked for a repeat run.  New uuid: `{new_uuid}`")

@bot.command(description="Get details of a render request")
async def query(ctx, uuid):
    with get_database() as client:
        result = client.database.get_collection("queue").find_one({"uuid": uuid})
        await ctx.respond(f"""```
        {json.loads(dumps(result))}
        ```""")

@bot.command(description="View queue statistics")
async def queuestats(ctx):
    embed = discord.Embed(
        title="Queue Stats",
        description="The following are the current queue statistics",
        color=discord.Colour.blurple(),
    )
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        # jobCount = queueCollection.count_documents({"status": {"$nin": ["archived","rejected"]}})
        queuedCount = queueCollection.count_documents({"status": "queued"})
        processingCount = queueCollection.count_documents({"status": "processing"})
        renderedCount = queueCollection.count_documents({"status": "archived"})
        rejectedCount = queueCollection.count_documents({"status": "rejected"})
        summary = f"""
        - ⚒️ Running: `{processingCount}`
        - ⌛ Waiting: `{queuedCount}`
        - 🖼️ Completed `{renderedCount}`
        - 🪲 Rejected `{rejectedCount}`
        """
        embed.add_field(name="Queue Stats", value=summary, inline=False)
        await ctx.respond(embed=embed)

@bot.command(description="View next 5 render queue entries")
async def queue(ctx):
    with get_database() as client:
        queue = client.database.get_collection("queue").find({"$query": {"status": {"$nin": ["archived","rejected"]}}, "$orderby": {"timestamp": -1}}).limit(5)
        # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
        embed = discord.Embed(
            title="Request Queue",
            description="The following requests are queued up.",
            color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
        )
        for j, job in enumerate(queue):
            user = await bot.fetch_user(job.get("author"))
            summary = f"""
            - 🧑‍🦲 Author: <@{job.get('author')}>
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
        description="The following agents appear active:",
        color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
    )

    with get_database() as client:
        agents = client.database.get_collection("agents").find()

        for a, agent in enumerate(agents):
            embed.add_field(name=agent.get("agent_id"), value=f"- Last Seen: `{agent.get('last_seen')}`", inline=False)
        await ctx.respond(embed=embed)


if __name__ == "__main__":
    print(discord.__version__)
    from discord.ext import tasks, commands

    bot.run(os.getenv("DISCORD_TOKEN"))
