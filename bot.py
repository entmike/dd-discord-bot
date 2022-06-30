import random
import requests
import traceback
import datetime
from random import choices
import math
import discord, os, subprocess
from discord.ext import tasks
from discord.ui import InputText, Modal
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
from loguru import logger
from texttable import Texttable

warnings.filterwarnings("ignore")
# from profanity_check import predict_prob

load_dotenv()

BOT_API = os.getenv("BOT_API")
BOT_PUBLIC_API = os.getenv("BOT_PUBLIC_API")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = os.getenv("BOT_NAME")
BOT_WEBSITE = os.getenv("BOT_WEBSITE")
BOT_ICON = os.getenv("BOT_ICON")

DISCORD_SERVER_ID = int(os.getenv("DISCORD_SERVER_ID"))
DISCORD_DAY_DREAMS = int(os.getenv("DISCORD_DAY_DREAMS"))
DISCORD_SKETCHES = int(os.getenv("DISCORD_SKETCHES"))
DISCORD_MUTATIONS = int(os.getenv("DISCORD_MUTATIONS"))
DISCORD_IMAGES = int(os.getenv("DISCORD_IMAGES"))
DISCORD_ACTIVE_JOBS = int(os.getenv("DISCORD_ACTIVE_JOBS"))
DISCORD_WAITING_JOBS = int(os.getenv("DISCORD_WAITING_JOBS"))
DISCORD_QUEUE_STATS = int(os.getenv("DISCORD_QUEUE_STATS"))
DISCORD_AGENT_STATS = int(os.getenv("DISCORD_AGENT_STATS"))
DISCORD_QUEUE_STATS_MSG = int(os.getenv("DISCORD_QUEUE_STATS_MSG"))
DISCORD_AGENT_STATS_MSG = int(os.getenv("DISCORD_AGENT_STATS_MSG"))
DISCORD_UPLOAD_FILES = bool(os.getenv("DISCORD_UPLOAD_FILES", True))
UPLOAD_FOLDER= str(os.getenv("UPLOAD_FOLDER", "images"))
STEP_LIMIT = int(os.getenv("STEP_LIMIT", 150))
PROFANITY_THRESHOLD = float(os.getenv("PROFANITY_THRESHOLD", 0.7))
AUTHOR_LIMIT = int(os.getenv("AUTHOR_LIMIT", 2))

intents = discord.Intents.default()
intents.members = True
bot = discord.Bot(debug_guilds=[DISCORD_SERVER_ID], intents=intents)  # specify the guild IDs in debug_guilds
arr = []
agents = []
ticks = 0


def updateJob(data):
    """
    Updates a Job by `uuid` via API call.
    """
    api = f"{BOT_API}/updatejob"
    logger.info(f"🌍 Updating Job '{api}'...")
    try:
        r = requests.post(api, data=data, headers={"x-dd-bot-token": BOT_TOKEN}, timeout=10).json()
        logger.info("Job updated.")
    except:
        logger.info("Update Job timed out.")
        r = None
    return r

def updateUser(data):
    """
    Updates a User by `id` via API call.
    """
    api = f"{BOT_API}/updateuser"
    logger.info(f"🌍 Updating User '{api}'...")
    logger.info(data)
    return requests.post(api, data=data, headers={"x-dd-bot-token": BOT_TOKEN}).json()

def lazy(obj, field):
    if obj.has_key(field):
        return obj[field]
    else:
        return None


async def queueBroadcast(who, status, author=None, channel=None, label="queue"):
    messageid = None
    subject = requests.get(f"{BOT_API}/serverinfo/{label}").json()
    if subject:
        channel = int(subject["channel"])
        messageid = int(subject["message"])
    channelid = channel
    channel = bot.get_channel(channelid)
    # Get data from API
    api = f"{BOT_API}/queue/{status}"
    logger.info(f"🌍 Getting queue from '{api}'...")
    queue = requests.get(api).json()
    color = discord.Colour.blurple()
    if status == "processing":
        color = discord.Colour.green()

    embed = discord.Embed(
        title="Request Queue",
        description=f"The following requests are {status}",
        color=color,  # Pycord provides a class with default colors you can choose from
    )
    embed.set_footer(text=f"Last update: {datetime.datetime.now()}")
    for j, job in enumerate(queue):
        user = await bot.fetch_user(job.get("author"))
        summary = f"""
        - 🧑‍🦲 Author: <@{job.get('author')}>
        - ✍️ Text Prompt: `{job.get('text_prompt')[0:100]}...`
        - Mode: `{job.get('mode')}`
        - Status: `{job.get('status')}`
        - Progress: `{job.get('percent')}%`
        - Timestamp: `{job.get('timestamp')}`
        - Agent: `{job.get('agent_id')}`
        """
        msgid = job.get("progress_msg")
        details = f"[Job]({BOT_API}/job/{job.get('uuid')})"
        summary = f"<@{job.get('author')}> | `{job.get('render_type')}` | `{job.get('percent')}%` | `{job.get('agent_id')}` | {details}"
        if msgid:
            if job.get("channel_id"):
                channel_id = job.get("channel_id")
            else:
                # bw compatibility
                if job.get("render_type") == "render" or job.get("render_type") == "repeat":
                    channel_id = DISCORD_IMAGES
                if job.get("render_type") == "mutate":
                    channel_id = DISCORD_MUTATIONS
                if job.get("render_type") == "sketch":
                    channel_id = DISCORD_SKETCHES
                if job.get("render_type") == "dream":
                    channel_id = DISCORD_DAY_DREAMS
            summary = f"{summary} | [Image](https://discord.com/channels/{DISCORD_SERVER_ID}/{channel_id}/{msgid})"
        embed.add_field(name=f"{job.get('uuid')}", value=summary, inline=False)
    if messageid != None:
        try:
            message = await channel.fetch_message(messageid)
            await message.edit(embed=embed)
        except:
            logger.info(f"{messageid} not found.  Creating new one.")
            msg = await channel.send(embed=embed)
            messageid = msg.id
            requests.post(f"{BOT_API}/serverinfo", headers={"x-dd-bot-token": BOT_TOKEN}, data={"subject": label, "channel": int(channelid), "message": int(messageid)}).json()
    else:
        msg = await channel.send(embed=embed)
        messageid = msg.id
        requests.post(f"{BOT_API}/serverinfo", headers={"x-dd-bot-token": BOT_TOKEN}, data={"subject": label, "channel": int(channelid), "message": int(messageid)}).json()


async def queue_status(channel=None, messageid=None):
    channel = bot.get_channel(channel)
    api = f"{BOT_API}/queuestats"
    logger.info(f"🌍 Getting queue stats from '{api}'...")
    queuestats = requests.get(api).json()

    embed = discord.Embed(
        title="Queue Stats",
        description="The following are the current queue statistics",
        color=discord.Colour.blurple(),
    )

    summary = f"""
    - ⚒️ Running: `{queuestats['processingCount']}`
    - ⌛ Waiting: `{queuestats['queuedCount']}`
    - 🖼️ Completed `{queuestats['completedCount']}`
    - 🖼️ Archived `{queuestats['renderedCount']}`
    - 🪲 Rejected `{queuestats['rejectedCount']}`
    """
    embed.add_field(name="Queue Stats", value=summary, inline=False)
    embed.set_footer(text=f"Last update: {datetime.datetime.now()}")
    if messageid != None:
        message = await channel.fetch_message(messageid)
        await message.edit(embed=embed)
    else:
        await channel.send(embed=embed)


# this code will be executed every 10 seconds after the bot is ready
@tasks.loop(seconds=10)
async def task_loop():
    global ticks
    ticks += 1
    botspam_channels = ["botspam"]
    logger.info("loop")
    # Queue Stats
    logger.info("Updating Queue Stats")
    await queue_status(DISCORD_QUEUE_STATS, DISCORD_QUEUE_STATS_MSG)
    # Agents
    logger.info("Updating Agent Status")
    await agent_status()
    # Active
    logger.info("Updating Active Queue")
    await queueBroadcast("all", "processing", None, DISCORD_ACTIVE_JOBS, "active")
    # Waiting
    logger.info("Updating Waiting Queue")
    await queueBroadcast("all", "queued", None, DISCORD_WAITING_JOBS, "waiting")
    # Process any Events
    logger.info("checking events")
    api = f"{BOT_API}/events"
    logger.info(f"🌍 Getting events from '{api}'...")
    events = requests.get(api, headers={"x-dd-bot-token": BOT_TOKEN}).json()
    logger.info(f"🌍 Clearing events from '{api}'...")
    api = f"{BOT_API}/clearevents"
    requests.get(api, headers={"x-dd-bot-token": BOT_TOKEN})

    logger.info(f"Processing {len(events)} events...")
    for event in events:
        # logger.info("event")
        title = "Message"
        embed = discord.Embed(
            title="Event",
            description=event.get("event"),
            color=discord.Colour.blurple(),
        )
        # for channel in botspam_channels:
        #     channel = discord.utils.get(bot.get_all_channels(), name=channel)
        # await channel.send(embed=embed)
        event_type = event.get("event")["type"]
        if event_type == "progress" or event_type == "preview":
            job_uuid = event.get("event")["job_uuid"]
            # logger.info(job_uuid)
            # logger.info(f"Progress Update found for {job_uuid}")
            api = f"{BOT_API}/job/{job_uuid}"
            # logger.info(f"🌍 Getting job from '{api}'...")
            job = requests.get(api).json()
            if job.get("last_preview"):
                # logger.info(type(job.get("last_preview")))
                if type(job.get("last_preview")) is str:
                    strdate = job.get("last_preview")
                    last_preview = datetime.datetime.strptime(strdate, "%Y-%m-%d %H:%M:%S.%f")
                else:
                    strdate = job.get("last_preview")["$date"]
                    try:
                        last_preview = datetime.datetime.strptime(strdate, "%Y-%m-%dT%H:%M:%S.%fZ")
                    except:
                        last_preview = datetime.datetime.strptime(strdate, "%Y-%m-%dT%H:%M:%SZ")
            else:
                last_preview = None
            # last_preview = datetime.datetime(job.get("last_preview")["$date"])
            toosoon = False
            if last_preview == None:
                toosoon = False
            else:
                n = datetime.datetime.now()
                duration = n - last_preview
                # logger.info(duration)
                if duration.total_seconds() < 60:
                    toosoon = True
                if job:
                    if job.get("status") == "processing" and toosoon == False:
                        updateJob({"uuid": job_uuid, "last_preview": datetime.datetime.now()})
                        embed, file, view = retrieve(job_uuid)
                        if embed:
                            logger.info(f"⬆️ Updating progress in discord for {job.get('uuid')}")
                            render_type = job.get("render_type")
                            if render_type is None:
                                render_type = "render"
                            if render_type == "sketch":
                                channel = "sketches"
                            if render_type == "render":
                                channel = "images"
                            if render_type == "mutate":
                                channel = "mutations"
                            if render_type == "dream":
                                channel = "day-dreams"

                            logger.info(f"🤩 {channel}")
                            channel = discord.utils.get(bot.get_all_channels(), name=channel)
                            # logger.info(f"Updating message {job.get('progress_msg')}...")
                            try:
                                if job.get("progress_msg"):
                                    msgid = job.get("progress_msg")
                                else:
                                    msg = await channel.send(embed=embed, view=view)
                                    updateJob({"uuid": job.get("uuid"), "progress_msg": msg.id})
                                    msgid = msg.id
                                message = await channel.fetch_message(msgid)
                                if file:
                                    if DISCORD_UPLOAD_FILES:
                                        await message.edit(file=file, view=view, embed=embed)
                                    else:
                                        await message.edit(embed=embed, view=view)
                                else:
                                    await message.edit(embed=embed, view=view)
                            except:
                                # logger.error(f"Could not update message {job.get('progress_msg')}")
                                pass
            # Acknowledge (delete) event
            # api = f"{BOT_API}/ack_event/{event.get('uuid')}"
            # requests.get(api, headers={"x-dd-bot-token": BOT_TOKEN}).json()

    # Display any new messages
    api = f"{BOT_API}/logs/"
    logger.info(f"🌍 Getting logs from '{api}'...")
    logs = requests.get(api).json()
    for message in logs:
        title = "Message"
        if message.get("title"):
            title = message.get(title)
        print(title)
        embed = discord.Embed(
            title=title,
            description=message.get("message"),
            color=discord.Colour.blurple(),
        )
        for channel in botspam_channels:
            channel = discord.utils.get(bot.get_all_channels(), name=channel)
            msg = await channel.send(embed=embed)

        api = f"{BOT_API}/ack_log/{message.get('uuid')}/"
        logger.info(f"🌍 Ack log '{message.get('uuid')}'...")
        requests.get(api, headers={"x-dd-bot-token": BOT_TOKEN}).json()

    # Display any completed jobs

    api = f"{BOT_API}/queue/complete/"
    logger.info(f"🌍 Getting completed jobs from '{api}'...")
    completedJobs = requests.get(api).json()
    if len(completedJobs) == 0:
        logger.info("No completed jobs.")
    else:
        logger.info(f"{len(completedJobs)} found...")
        for completedJob in completedJobs:
            logger.info(f"Found completed job: {completedJob.get('uuid')} | Render Type: {completedJob.get('render_type')}")

            render_type = completedJob.get("render_type")

            if render_type is None:
                render_type = "render"
            if render_type == "sketch":
                channel = "sketches"
            if render_type == "render":
                channel = "images"
            if render_type == "mutate":
                channel = "mutations"
            if render_type == "dream":
                channel = "day-dreams"
            channels = ["images-discussion", channel]

            for channel in channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                try:
                    embed, file, view = retrieve(completedJob.get("uuid"))
                    if completedJob.get("progress_msg"):
                        try:
                            message = await channel.fetch_message(completedJob.get("progress_msg"))
                        except:
                            message = None
                        if message:
                            if DISCORD_UPLOAD_FILES:
                                # Not sure why, but it fixes images showing up outside of embed
                                await message.edit(view=view, file=file, embed=embed)
                                # await message.edit(embed=embed)
                            else:
                                await message.edit(embed=embed, view=view)
                        else:
                            logger.info(f"Sending new message to {channel.name}")
                            await channel.send(embed=embed, view=view, file=file)
                    else:
                        if DISCORD_UPLOAD_FILES:
                            await channel.send(embed=embed, view=view, file=file)
                        else:
                            await channel.send(embed=embed, view=view)
                except Exception as e:
                    tb = traceback.format_exc()
                    await channel.send(f"💀 Cannot display {completedJob.get('uuid')}\n`{tb}`")
            updateJob({"uuid": completedJob.get("uuid"), "status": "archived"})

    # Display any failed jobs

    api = f"{BOT_API}/queue/failed"
    logger.info(f"🌍 Getting failed jobs from '{api}'...")
    failedJobs = requests.get(api).json()
    if len(failedJobs) == 0:
        logger.info("No failures found.")
    else:
        for failedJob in failedJobs:
            for channel in botspam_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                embed = discord.Embed(
                    title="😭 Failure 😭",
                    description=f"Job `{failedJob.get('uuid')}` failed, <@{failedJob.get('author')}>!  Blame `{failedJob.get('agent_id')}`",
                    color=discord.Colour.blurple(),
                )
                tb = failedJob.get("traceback")
                if tb:
                    tb = tb[-600:]
                    embed.add_field(name="Traceback", value=f"```{tb}```", inline=False)

                log = failedJob.get("log")
                if log:
                    log = log[-300:]
                    embed.add_field(name="Log", value=f"```{log}```", inline=False)
                # embed, file, view = retrieve(failedJob.get('uuid'))
                await channel.send(embed=embed)
            rejectedCount = failedJob.get("reject_count")
            if rejectedCount:
                rejectedCount += 1
            else:
                rejectedCount = 0
            updateJob({"uuid": failedJob.get("uuid"), "status": "rejected", "rejectedCount": rejectedCount})

    # Drop any stalled jobs

    api = f"{BOT_API}/queue/stalled"
    logger.info(f"🌍 Getting stalled jobs from '{api}'...")
    stalls = requests.get(api).json()
    for stall in stalls:
        for channel in botspam_channels:
            channel = discord.utils.get(bot.get_all_channels(), name=channel)
            embed = discord.Embed(
                title="😠 Job Stalled 😠",
                description=f"Job `{stall.get('uuid')}` from <@{stall.get('author')}> was apparently abandoned by `{stall.get('agent_id')}`  Reassigning in queue.",
                color=discord.Colour.orange(),
            )
            await channel.send(embed=embed)
        updateJob({"uuid": stall.get("uuid"), "status": "queued", "agent_id": None, "percent": None, "last_preview": None, "timestamp": datetime.datetime.now()})
     # Drop any events for performance
    logger.info("end loop")


class MyModal(Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(InputText(label="Short Input", placeholder="Placeholder Test"))

        self.add_item(
            InputText(
                custom_id="text_prompt",
                label="Text Prompt",
                value="lighthouses on artstation",
                style=discord.InputTextStyle.long,
            )
        )
        self.add_item(
            InputText(
                label="Steps",
                custom_id="steps",
                value=150,
                style=discord.InputTextStyle.short,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Your Modal Results", color=discord.Color.random())
        embed.add_field(name="First Input", value=self.children[0].value, inline=False)
        embed.add_field(name="Second Input", value=self.children[1].value, inline=False)
        await interaction.response.send_message(embeds=[embed])


@bot.slash_command(name="refresh", description="Refresh an image (temporary utility command)")
async def refresh(ctx, job_uuid):
    await ctx.respond("Acknowledged.", ephemeral=True)
    await do_refresh(job_uuid)

@discord.ext.commands.has_any_role("admin")
@bot.slash_command(name="refresh_all", description="Refresh all images (temporary utility command)")
async def refresh_all(ctx):
    await ctx.respond("Acknowledged.", ephemeral=True)
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        jobs = queueCollection.find({})
        max = 10000000
        m = 0
        for job in jobs:
            if(job.get('progress_msg')):
                m += 1
                if m < max:
                    do_refresh(job.get('uuid'))
                else:
                    logger.info(f"{job.get('uuid')} max update reached...")
            else:
                logger.info("no")

async def do_refresh(job_uuid):
    embed, file, view = retrieve(job_uuid)
    logger.info(job_uuid)
    channels = ["images", "sketches", "images-discussion"]
    job = requests.get(f"{BOT_API}/job/{job_uuid}").json()
    if job:
        logger.info(f"{job_uuid} being refreshed in Discord...")
        for channel in channels:
            channel = discord.utils.get(bot.get_all_channels(), name=channel)
            embed, file, view = retrieve(job_uuid)
            try:
                msgid = job.get("progress_msg")
                if msgid:
                    try:
                        message = await channel.fetch_message(msgid)
                    except:
                        message = None
                    if message:
                        if DISCORD_UPLOAD_FILES:
                            await message.edit(embed=embed, view=view, file=file)
                        else:
                            await message.edit(embed=embed, view=view)
                        logger.info(f"{job_uuid} has been refreshed in message {msgid} on Discord...")
                    # else:
                    #     await channel.send(embed=embed, view=view, file=file)
                # else:
                #     await channel.send(embed=embed, view=view, file=file)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"💀 Cannot display {job_uuid}\n`{tb}`")
                # await channel.send(f"💀 Cannot display {job_uuid}\n`{tb}`")


@bot.slash_command(name="display")
async def display(ctx, job_uuid):
    embed, file, view = retrieve(job_uuid)
    try:
        if DISCORD_UPLOAD_FILES:
            await ctx.respond(embed=embed, view=view, file=file)
        else:
            await ctx.respond(embed=embed, view=view)
    except:
        await ctx.respond(f"💀 Cannot display {job_uuid}")


@bot.slash_command(name="logs")
async def logs(ctx, job_uuid):
    embed, file, view = retrieve_log(job_uuid)
    if file:
        await ctx.respond(embed=embed, file=file, view=view)
    else:
        await ctx.respond("No log could be found for this run.  It probably crashed hard.")


def retrieve_log(uuid):
    job = requests.get(f"{BOT_API}/job/{uuid}").json()
    if job:
        embed = discord.Embed(
            description=f"Attached is the GPU run log for you, nerd:\n`{uuid}`",
            color=discord.Colour.blurple(),
        )
        view = discord.ui.View()
        if job.get("log"):
            file = discord.File(f"{UPLOAD_FOLDER}/{job.get('log')}", filename=job.get("log"))
        else:
            file = None
        return embed, file, view
    else:
        return None, None, None


def retrieve(uuid):
    # logger.info(f"Retrieving {uuid}")
    job = requests.get(f"{BOT_API}/job/{uuid}").json()
    if not job:
        return None, None, None
    try:
        duration = job.get("duration")
        if duration == None:
            duration = 0
    except:
        duration = 0

    preview = job.get("preview")
    status = job.get("status")
    percent = job.get("percent")

    color = discord.Colour.blurple()
    if percent == None:
        percent = 0
    if status == "archived" or status == "complete":
        color = discord.Colour.green()
    if status == "processing":
        color = discord.Colour.green()
    if status == "queued":
        color = discord.Colour.blurple()
    # logger.info(f"{uuid} - {status}")
    details = f"[Job]({BOT_API}/job/{job.get('uuid')}) | [Config]({BOT_API}/config/{job.get('uuid')}) | [Web]({BOT_WEBSITE}/piece/{job.get('uuid')})"
    if job.get("parent_uuid"):
        details = f"{details} | Parent: `{job.get('parent_uuid')}`"
    embed = discord.Embed(
        # description=,
        color=color,
        fields=[
            discord.EmbedField("Author", f"<@{job.get('author')}>", inline=True),
            discord.EmbedField("Type", f"`{job.get('render_type')}`", inline=True),
            discord.EmbedField("Model", f"`{job.get('model')}`", inline=True),
            discord.EmbedField("Steps", f"`{str(job.get('steps'))}`", inline=True),
            discord.EmbedField("Progress", f"`{str(percent)}%`", inline=True),
            discord.EmbedField("Text Prompt", f"`{job.get('text_prompt')[:500]}`", inline=False),
            discord.EmbedField("Details", details, inline=True)
            # discord.EmbedField("Steps", f"`{completedJob.get('steps')}`", inline=True),
            # discord.EmbedField("CLIP Model", f"`{completedJob.get('model')}`", inline=True),
            # discord.EmbedField("Diffusion Model", f"`{completedJob.get('diffusion_model')}`", inline=True),
            # discord.EmbedField("Shape", f"`{completedJob.get('shape')}`", inline=True),
            # discord.EmbedField("Inner Cut Power", f"`{completedJob.get('cut_ic_pow')}`", inline=True),
            # discord.EmbedField("Saturation Scale", f"`{completedJob.get('sat_scale')}`", inline=True),
            # discord.EmbedField("CLIP Guidance Scale", f"`{completedJob.get('clip_guidance_scale')}`", inline=True),
            # discord.EmbedField("Cut Schedule", f"`{completedJob.get('cut_schedule')}`", inline=True),
            # discord.EmbedField("Clamp Max", f"`{str(completedJob.get('clamp_max'))}`", inline=True),
            # discord.EmbedField("Seed", f"`{str(completedJob.get('set_seed'))}`", inline=True),
            # discord.EmbedField("Symmetry", f"`{str(completedJob.get('symmetry'))}`", inline=True),
            # discord.EmbedField("Symmetry Loss Scale", f"`{str(completedJob.get('symmetry_loss_scale'))}`", inline=True),
            # discord.EmbedField("Duration (sec)", f"`{str(math.floor(duration))}`", inline=True),
            # discord.EmbedField("Memory HWM", f"`{str(completedJob.get('mem_hwm'))}`", inline=True)
        ],
    )
    embed.set_author(
        name=job.get('uuid'),
        icon_url=BOT_ICON,
    )
    embed.set_footer(text=f"Render time: {str(math.floor(duration))} sec")

    view = discord.ui.View()
    pinButton = discord.ui.Button(label="Toggle as Favorite", style=discord.ButtonStyle.green, emoji="📌", custom_id=job.get("uuid"))
    pinButton.callback = pinCallback
    # view.add_item(pinButton)
    preview = job.get("preview")
    fn = ""
    if preview == True:
        fn = f"{uuid}_progress.png"
    if status == "archived" or status == "complete":
        fn = job.get("filename")
    if fn != "":
        if DISCORD_UPLOAD_FILES:
            # logger.info(f"Uploading {fn}...")
            file = discord.File(f"{UPLOAD_FOLDER}/{fn}", fn)
            embed.set_image(url=f"attachment://{fn}")
            # logger.info(f"Upload of {fn} complete.")
        else:
            file = None
            embed.set_image(url=f"{BOT_PUBLIC_API}/image/{uuid}")
    else:
        file = None
    return embed, file, view


async def pinCallback(interaction):
    logger.info(interaction)
    job = requests.get(f"{BOT_API}/job/{interaction.custom_id}").json()
    if job:
        r = requests.get(f"{BOT_API}/toggle_pin/{interaction.user.id}/{interaction.custom_id}", headers={"x-dd-bot-token": BOT_TOKEN}).json()["message"]
        await interaction.response.send_message(f"{interaction.user.mention} {interaction.custom_id} {r}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Cannot find {interaction.custom_id} to pin.", ephemeral=True)


@bot.slash_command(name="modaltest")
async def modal_slash(ctx):
    """Shows an example of a modal dialog being invoked from a slash command."""
    modal = MyModal(title="Slash Command Modal")
    await ctx.send_modal(modal)


@bot.command(description="Please HALP")
async def help(
    ctx,
    term: discord.Option(
        str,
        "Term",
        required=False,
        default="help",
        choices=[
            discord.OptionChoice("Text Prompts", value="text_prompts"),
            discord.OptionChoice("Steps", value="steps"),
            discord.OptionChoice("CLIP Guidance Scale", value="clip_guidance_scale"),
            discord.OptionChoice("Inner Cut Power", value="cut_ic_pow"),
            discord.OptionChoice("Cut Schedule", value="cut_schedule"),
            discord.OptionChoice("Clamp Max", value="clamp_max"),
            discord.OptionChoice("Seed", value="set_seed"),
        ],
    ),
):
    help = ""
    if term == "cut_schedule":
        help = """
        **`cut_schedule` controls 2 DD parameters:**
        
        `cut_overview`: The schedule of overview cuts
        `cut_innercut`: The schedule of inner cuts

        **Values:**

        **`default`**:
        `cut_overview` : `"[12]*400+[4]*600"`
        `cut_innercut` : `"[4]*400+[12]*600"`

        **'detailed-a'**
        `cut_overview` : `"[10]*200+[8]*200+[6]*200+[2]*200+[2]*200"`
        `cut_innercut` : `"[0]*200+[2]*200+[6]*200+[8]*200+[10]*200"`

        **`detailed-b`**
        `cut_overview` : `"[10]*200+[8]*200+[6]*200+[4]*200+[2]*200"`
        `cut_innercut` : `"[2]*200+[2]*200+[8]*200+[8]*200+[10]*200"`

        **`ram_efficient`**
        `cut_overview` : `"[10]*200+[8]*200+[5]*200+[2]*200+[2]*200"`
        `cut_innercut` : `"[0]*200+[2]*200+[5]*200+[7]*200+[9]*200"`
        """
    if term == "clamp_max":
        help = """
        Sets the value of the clamp_grad limitation. Default is 0.05, providing for smoother, more muted coloration in images, but setting higher values `(0.15-0.3)` can provide interesting contrast and vibrancy.
        """
    if term == "text_prompts":
        help = """
        Phrase, sentence, or string of words and phrases describing what the image should look like.  The words will be analyzed by the AI and will guide the diffusion process toward the image(s) you describe. These can include commas and weights to adjust the relative importance of each element.  E.g. "A beautiful painting of a singular lighthouse, shining its light across a tumultuous sea of blood by greg rutkowski and thomas kinkade, Trending on artstation."
        """
    if term == "cut_ic_pow":
        help = """
        This sets the size of the border used for inner cuts.  High cut_ic_pow values have larger borders, and therefore the cuts themselves will be smaller and provide finer details.  If you have too many or too-small inner cuts, you may lose overall image coherency and/or it may cause an undesirable 'mosaic' effect.   Low cut_ic_pow values will allow the inner cuts to be larger, helping image coherency while still helping with some details.
        """
    if term == "steps":
        help = """
        When creating an image, the denoising curve is subdivided into steps for processing. Each step (or iteration) involves the AI looking at subsets of the image called "cuts" and calculating the "direction" the image should be guided to be more like the prompt. Then it adjusts the image with the help of the diffusion denoiser, and moves to the next step.

        Increasing steps will provide more opportunities for the AI to adjust the image, and each adjustment will be smaller, and thus will yield a more precise, detailed image. Increasing steps comes at the expense of longer render times. Also, while increasing steps should generally increase image quality, there is a diminishing return on additional steps beyond 250 - 500 steps. However, some intricate images can take 1000, 2000, or more steps. It is really up to the user.
        """
    if term == "help":
        help = "Yo dog, I heard you needed help so I put help in your help."

    if term == "clip_guidance_scale":
        help = f"""
        CGS is one of the most important parameters you will use. It tells DD how strongly you want CLIP to move toward your prompt each timestep.  Higher is generally better, but if CGS is too strong it will overshoot the goal and distort the image. So a happy medium is needed, and it takes experience to learn how to adjust CGS. 
 
        Note that this parameter generally scales with image dimensions. In other words, if you increase your total dimensions by `50%` (e.g. a change from `512 x 512` to `512 x 768`), then to maintain the same effect on the image, you’d want to increase `clip_guidance_scale` from `5000` to `7500`.
        """
    embed = discord.Embed(title=f"{term}", color=discord.Color.random(), description=help)
    await ctx.respond(embed=embed)


@bot.command(description="Sends the bot's latency.")  # this decorator makes a slash command
async def ping(ctx):  # a slash command will be created with the name "ping"
    await ctx.respond(f"Pong! Latency is {bot.latency}")


@bot.event
async def on_ready():
    logger.info(f"{bot.user} is ready and online!")
    members = await bot.guilds[0].fetch_members(limit=1000).flatten()

    for member in members:
        logger.info(member.id)
        logger.info(member.name)
        av = member.avatar
        if av:
            uri = av.url
        else:
            uri = ""
        updateUser({
            "user_id": int(member.id),
            "user_name" : member.name,
            "display_name" : member.display_name,
            "discriminator" : member.discriminator,
            "nick" : member.nick,
            "avatar" : uri,
            #"display_avatar" : member.display_avatar
        })

    task_loop.start()  # important to start the loop


@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server, {member.mention}! Enjoy your stay here.  Type `/render` to get started.")


async def do_render(
    ctx,
    render_type,
    text_prompt,
    steps,
    shape,
    model,
    clip_guidance_scale,
    cut_ic_pow,
    sat_scale,
    clamp_max,
    set_seed,
    symmetry,
    symmetry_loss_scale,
    cut_schedule,
    diffusion_model,
    eta,
    cutn_batches,
    parent_uuid,
):
    reject = False
    reasons = []
    # with get_database() as client:
    #     queueCollection = client.database.get_collection("queue")
    #     query = {"author": int(ctx.author.id), "status": {"$nin": ["archived","rejected"]}}
    #     jobCount = queueCollection.count_documents(query)
    #     if jobCount >= AUTHOR_LIMIT:
    #         reject = True
    #         reasons.append(f"- ❌ You have too many jobs queued (`{jobCount}`).  Wait until your queued job count is under {AUTHOR_LIMIT} or remove an existing with /remove command.")

    if steps > STEP_LIMIT:
        reject = True
        reasons.append(f"- ❌ Too many steps.  Limit your steps to {STEP_LIMIT}")
    # profanity = predict_prob([text_prompt])[0]
    # if profanity >= PROFANITY_THRESHOLD:
    #     reject = True
    #     reasons.append(f"- ❌ Profanity detected.  Watch your fucking mouth.")
    if not reject:
        api = f"{BOT_API}/placeorder"
        logger.info(f"🌍 Placing Order at '{api}'...")
        job_uuid = str(uuid.uuid4())
        text_prompt = text_prompt.replace("“", '"')
        text_prompt = text_prompt.replace("”", '"')
        if set_seed == -1:
            seed = random.randint(0, 2**32)
        else:
            seed = int(set_seed)
        record = {
            "uuid": job_uuid,
            "parent_uuid": parent_uuid,
            "render_type": render_type,
            "text_prompt": text_prompt,
            "steps": steps,
            "shape": shape,
            "model": model,
            "diffusion_model": diffusion_model,
            "symmetry": symmetry,
            "symmetry_loss_scale": symmetry_loss_scale,
            "cut_schedule": cut_schedule,
            "clip_guidance_scale": clip_guidance_scale,
            "clamp_max": clamp_max,
            "set_seed": seed,
            "cut_ic_pow": cut_ic_pow,
            "cutn_batches": cutn_batches,
            "sat_scale": sat_scale,
            "author": int(ctx.author.id),
            "status": "queued",
            "eta": eta,
        }

        r = requests.post(api, data=record, headers={"x-dd-bot-token": BOT_TOKEN})
        embed, file, view = retrieve(job_uuid)

        if render_type is None:
            render_type = "render"
        if render_type == "sketch":
            channel = "sketches"
        if render_type == "render":
            channel = "images"
        if render_type == "mutate":
            channel = "mutations"
        if render_type == "dream":
            channel = "day-dreams"

        channel = discord.utils.get(bot.get_all_channels(), name=channel)
        msg = await channel.send(embed=embed, view=view)

        updateJob({"uuid": job_uuid, "progress_msg": msg.id})

        await ctx.respond("Command Accepted.", ephemeral=True)

    else:
        await ctx.respond("\n".join(reasons), ephemeral=True)


@bot.command(description="Make a dream")
async def dream(
    ctx,
    dream: discord.Option(str, "Enter your dream", required=True),
):
    api = f"{BOT_API}/dream"
    logger.info(f"🌍 Changing Dream '{api}'...")
    u = requests.post(api, data={"author_id": ctx.author.id, "dream": dream}, headers={"x-dd-bot-token": BOT_TOKEN}).json()
    await ctx.respond(f"🌛 Thanks! 🐑", ephemeral=True)


@bot.command(description="Stop dreaming")
async def wakeup(ctx):
    api = f"{BOT_API}/awaken/{ctx.author.id}"
    logger.info(f"🌍 Waking up '{api}'...")
    u = requests.get(api).json()
    await ctx.respond(f"🌄 I'm awake.  Dreams stopped. 👀", ephemeral=True)


@bot.command(description="Mutate a Disco Diffusion Render")
async def mutate(
    ctx,
    job_uuid: discord.Option(str, "Job UUID to mutate", required=True),
    text_prompt: discord.Option(str, "Enter your text prompt", required=False),
    steps: discord.Option(int, "Number of steps", required=False),
    cutn_batches: discord.Option(
        int,
        "Cut Batches",
        required=False,
        default=4,
        choices=[discord.OptionChoice("2", value=2), discord.OptionChoice("4", value=4), discord.OptionChoice("8", value=8), discord.OptionChoice("16", value=16)],
    ),
    shape: discord.Option(
        str,
        "Image Shape",
        required=False,
        choices=[
            discord.OptionChoice("Landscape", value="landscape"),
            discord.OptionChoice("Portrait", value="portrait"),
            discord.OptionChoice("Square", value="square"),
            discord.OptionChoice("Tiny Square", value="tiny-square"),
            discord.OptionChoice("Panoramic", value="pano"),
            discord.OptionChoice("Skyscraper", value="skyscraper"),
        ],
    ),
    model: discord.Option(
        str,
        "Models",
        required=False,
        choices=[
            discord.OptionChoice("Default (ViTB16+32, RN50)", value="default"),
            discord.OptionChoice("ViTB16+32, RN50x64", value="rn50x64"),
            discord.OptionChoice("ViTB16+32, ViTL14", value="vitl14"),
            discord.OptionChoice("ViTB16+32, ViTL14x336", value="vitl14x336"),
            discord.OptionChoice("RN50x64 and ViTL14x336", value="ludicrous"),
        ],
    ),
    clip_guidance_scale: discord.Option(int, "CLIP guidance scale", required=False),
    cut_ic_pow: discord.Option(int, "CLIP Innercut Power", required=False),
    sat_scale: discord.Option(int, "Saturation Scale", required=False),
    clamp_max: discord.Option(str, "Clamp Max", required=False),
    eta: discord.Option(str, "ETA", required=False),
    set_seed: discord.Option(int, "Seed", required=False),
    symmetry: discord.Option(
        str,
        "Symmetry",
        required=False,
        choices=[
            discord.OptionChoice("No", value="no"),
            discord.OptionChoice("Yes", value="yes"),
        ],
    ),
    cut_schedule: discord.Option(
        str,
        "Cut Schedule",
        required=False,
        choices=[
            discord.OptionChoice("Default", value="default"),
            discord.OptionChoice("Detailed A", value="detailed-a"),
            discord.OptionChoice("Detailed B", value="detailed-b"),
            discord.OptionChoice("RAM Efficient", value="ram-efficient"),
            discord.OptionChoice("Potato", value="potato"),
        ],
    ),
    diffusion_model: discord.Option(
        str,
        "Diffusion Model",
        required=False,
        choices=[
            discord.OptionChoice("512x512_diffusion_uncond_finetune_008100", value="512x512_diffusion_uncond_finetune_008100"),
            discord.OptionChoice("256x256_diffusion_uncond", value="256x256_diffusion_uncond"),
            discord.OptionChoice("pixel_art_diffusion_hard_256", value="pixel_art_diffusion_hard_256"),
            discord.OptionChoice("pixel_art_diffusion_soft_256", value="pixel_art_diffusion_soft_256"),
            discord.OptionChoice("256x256_openai_comics_faces_by_alex_spirin_084000", value="256x256_openai_comics_faces_by_alex_spirin_084000"),
            discord.OptionChoice("lsun_uncond_100M_1200K_bs128", value="lsun_uncond_100M_1200K_bs128"),
        ],
    ),
    symmetry_loss_scale: discord.Option(int, "Symmetry Loss Scale", required=False),
):

    result = requests.get(f"{BOT_API}/duplicate/{job_uuid}").json()

    if result:
        for param in [
            "text_prompt",
            "steps",
            "shape",
            "model",
            "clip_guidance_scale",
            "cut_ic_pow",
            "sat_scale",
            "clamp_max",
            "symmetry",
            "cut_schedule",
            "diffusion_model",
            "symmetry_loss_scale",
            "eta",
            "cutn_batches",
        ]:
            if locals()[param]:
                value = locals()[param]
                logger.info(f"Mutating {param} to {value}")
                result[param] = value
            else:
                if param in result:
                    logger.info(f"Keeping {param} as {result[param]}")
                else:
                    logger.info(f"{param} not present in original job.")
                    result[param] = None

        if set_seed == -1:
            seed = random.randint(0, 2**32)
        else:
            seed = result["set_seed"]

        result["set_seed"] = seed

        await do_render(
            ctx,
            "mutate",
            result["text_prompt"],
            result["steps"],
            result["shape"],
            result["model"],
            result["clip_guidance_scale"],
            result["cut_ic_pow"],
            result["sat_scale"],
            result["clamp_max"],
            seed,
            result["symmetry"],
            result["symmetry_loss_scale"],
            result["cut_schedule"],
            result["diffusion_model"],
            result["eta"],
            result["cutn_batches"],
            job_uuid,
        )
    else:
        await ctx.respond("😭 Hmm, couldn't find that one to mutate.")


@bot.command(description="Submit a Disco Diffusion Render Request")
async def render(
    ctx,
    text_prompt: discord.Option(str, "Text Prompt", required=True),
    steps: discord.Option(int, "Number of steps", required=False, default=150),
    cutn_batches: discord.Option(
        int,
        "Cut Batches",
        required=False,
        default=4,
        choices=[discord.OptionChoice("2", value=2), discord.OptionChoice("4", value=4), discord.OptionChoice("8", value=8), discord.OptionChoice("16", value=16)],
    ),
    shape: discord.Option(
        str,
        "Image Shape",
        required=False,
        default="landscape",
        choices=[
            discord.OptionChoice("Landscape", value="landscape"),
            discord.OptionChoice("Portrait", value="portrait"),
            discord.OptionChoice("Square", value="square"),
            discord.OptionChoice("Tiny Square", value="tiny-square"),
            discord.OptionChoice("Panoramic", value="pano"),
            discord.OptionChoice("Skyscraper", value="skyscraper"),
        ],
    ),
    model: discord.Option(
        str,
        "Models",
        required=False,
        default="default",
        choices=[
            discord.OptionChoice("Default (ViTB16+32, RN50)", value="default"),
            discord.OptionChoice("ViTB16+32, RN50x64", value="rn50x64"),
            discord.OptionChoice("ViTB16+32, ViTL14", value="vitl14"),
            discord.OptionChoice("ViTB16+32, ViTL14x336", value="vitl14x336"),
            discord.OptionChoice("RN50x64 and ViTL14x336", value="ludicrous"),
        ],
    ),
    clip_guidance_scale: discord.Option(int, "CLIP guidance scale", required=False, default=5000),
    cut_ic_pow: discord.Option(int, "CLIP Innercut Power", required=False, default=1),
    sat_scale: discord.Option(int, "Saturation Scale", required=False, default=0),
    clamp_max: discord.Option(str, "Clamp Max", required=False, default="0.05"),
    eta: discord.Option(str, "ETA", required=False, default="0.8"),
    set_seed: discord.Option(int, "Seed", required=False, default=-1),
    symmetry: discord.Option(
        str,
        "Symmetry",
        required=False,
        default="no",
        choices=[
            discord.OptionChoice("No", value="no"),
            discord.OptionChoice("Yes", value="yes"),
        ],
    ),
    cut_schedule: discord.Option(
        str,
        "Cut Schedule",
        required=False,
        default="default",
        choices=[
            discord.OptionChoice("Default", value="default"),
            discord.OptionChoice("Detailed A", value="detailed-a"),
            discord.OptionChoice("Detailed B", value="detailed-b"),
            discord.OptionChoice("RAM Efficient", value="ram-efficient"),
            discord.OptionChoice("Potato", value="potato"),
        ],
    ),
    diffusion_model: discord.Option(
        str,
        "Diffusion Model",
        required=False,
        default="512x512_diffusion_uncond_finetune_008100",
        choices=[
            discord.OptionChoice("512x512_diffusion_uncond_finetune_008100", value="512x512_diffusion_uncond_finetune_008100"),
            discord.OptionChoice("256x256_diffusion_uncond", value="256x256_diffusion_uncond"),
            discord.OptionChoice("pixel_art_diffusion_hard_256", value="pixel_art_diffusion_hard_256"),
            discord.OptionChoice("pixel_art_diffusion_soft_256", value="pixel_art_diffusion_soft_256"),
            discord.OptionChoice("256x256_openai_comics_faces_by_alex_spirin_084000", value="256x256_openai_comics_faces_by_alex_spirin_084000"),
            discord.OptionChoice("lsun_uncond_100M_1200K_bs128", value="lsun_uncond_100M_1200K_bs128"),
        ],
    ),
    symmetry_loss_scale: discord.Option(int, "Symmetry Loss Scale", required=False, default=1500),
):
    await do_render(
        ctx,
        "render",
        text_prompt,
        steps,
        shape,
        model,
        clip_guidance_scale,
        cut_ic_pow,
        sat_scale,
        clamp_max,
        set_seed,
        symmetry,
        symmetry_loss_scale,
        cut_schedule,
        diffusion_model,
        eta,
        cutn_batches,
        None,
    )


@bot.command(description="Submit a Disco Diffusion Sketch Request (will jump queue)")
async def sketch(
    ctx,
    text_prompt: discord.Option(str, "Enter your text prompt", required=True),
    shape: discord.Option(
        str,
        "Image Shape",
        required=False,
        default="landscape",
        choices=[
            discord.OptionChoice("Landscape", value="landscape"),
            discord.OptionChoice("Portrait", value="portrait"),
            discord.OptionChoice("Square", value="square"),
            discord.OptionChoice("Tiny Square", value="tiny-square"),
            discord.OptionChoice("Panoramic", value="pano"),
            discord.OptionChoice("Skyscraper", value="skyscraper"),
        ],
    ),
    clip_guidance_scale: discord.Option(int, "CLIP guidance scale", required=False, default=5000),
    cut_ic_pow: discord.Option(int, "CLIP Innercut Power", required=False, default=1),
    sat_scale: discord.Option(int, "Saturation Scale", required=False, default=0),
    clamp_max: discord.Option(str, "Clamp Max", required=False, default="0.05"),
    eta: discord.Option(str, "ETA", required=False, default="0.8"),
    set_seed: discord.Option(int, "Seed", required=False, default=-1),
    cutn_batches: discord.Option(
        int,
        "Cut Batches",
        required=False,
        default=2,
        choices=[
            discord.OptionChoice("2", value=2),
            discord.OptionChoice("4", value=4),
        ],
    ),
    steps: discord.Option(
        str,
        "Diffusion Model",
        required=False,
        default=50,
        choices=[
            discord.OptionChoice("50", value="50"),
            discord.OptionChoice("100", value="100"),
        ],
    ),
    symmetry: discord.Option(
        str,
        "Symmetry",
        required=False,
        default="no",
        choices=[
            discord.OptionChoice("No", value="no"),
            discord.OptionChoice("Yes", value="yes"),
        ],
    ),
    symmetry_loss_scale: discord.Option(int, "Symmetry Loss Scale", required=False, default=1500),
    cut_schedule: discord.Option(
        str,
        "Cut Schedule",
        required=False,
        default="default",
        choices=[
            discord.OptionChoice("Detailed A", value="detailed-a"),
            discord.OptionChoice("Detailed B", value="detailed-b"),
            discord.OptionChoice("RAM Efficient", value="ram-efficient"),
            discord.OptionChoice("Potato", value="potato"),
        ],
    ),
    diffusion_model: discord.Option(
        str,
        "Diffusion Model",
        required=False,
        default="512x512_diffusion_uncond_finetune_008100",
        choices=[
            discord.OptionChoice("512x512_diffusion_uncond_finetune_008100", value="512x512_diffusion_uncond_finetune_008100"),
            discord.OptionChoice("256x256_diffusion_uncond", value="256x256_diffusion_uncond"),
            discord.OptionChoice("pixel_art_diffusion_hard_256", value="pixel_art_diffusion_hard_256"),
            discord.OptionChoice("pixel_art_diffusion_soft_256", value="pixel_art_diffusion_soft_256"),
            discord.OptionChoice("256x256_openai_comics_faces_by_alex_spirin_084000", value="256x256_openai_comics_faces_by_alex_spirin_084000"),
            discord.OptionChoice("lsun_uncond_100M_1200K_bs128", value="lsun_uncond_100M_1200K_bs128"),
        ],
    ),
):
    await do_render(
        ctx,
        "sketch",
        text_prompt,
        int(steps),
        shape,
        "default",
        clip_guidance_scale,
        cut_ic_pow,
        sat_scale,
        clamp_max,
        set_seed,
        symmetry,
        symmetry_loss_scale,
        cut_schedule,
        diffusion_model,
        eta,
        cutn_batches,
        None,
    )


@bot.command(description="Remove a render request (intended for admins)")
@discord.ext.commands.has_any_role("admin")
async def destroy(ctx, uuid):
    job = requests.get(f"{BOT_API}/job/{uuid}").json()
    if job:
        if job.get("progress_msg"):
            await channel_erase(job)

        d = requests.delete(f"{BOT_API}/job/{uuid}").json()
        logger.info(d)
        count = d["deleted_count"]
        if count == 0:
            await ctx.respond(f"❌ Could not delete job `{uuid}`.  Check the Job ID.", ephemeral=True)
        else:
            await ctx.respond(f"🗑️ Job destroyed.", ephemeral=True)
    else:
        await ctx.respond(f"❌ Could not find job `{uuid}`.  Check the Job ID.", ephemeral=True)


@bot.command(description="Remove a render request")
async def remove(ctx, uuid):
    job = requests.get(f"{BOT_API}/job/{uuid}").json()
    if job:
        if job.get("progress_msg"):
            await channel_erase(job)
    d = requests.delete(f"{BOT_API}/cancel/{uuid}", data={"requestor": ctx.author.id}, headers={"x-dd-bot-token": BOT_TOKEN}).json()
    await ctx.respond(d["message"], ephemeral=True)


async def channel_erase(job):
    render_type = job.get("render_type")
    if render_type is None:
        render_type = "render"
    if render_type == "sketch":
        channel = "sketches"
    if render_type == "render":
        channel = "images"
    if render_type == "mutate":
        channel = "mutations"
    if render_type == "dream":
        channel = "day-dreams"
    channel = discord.utils.get(bot.get_all_channels(), name=channel)
    msg = await channel.fetch_message(job.get("progress_msg"))
    logger.info(f"{msg.id} deleted.")
    await msg.delete()


@bot.command(description="Retry a render request")
async def retry(ctx, uuid):
    job = requests.get(f"{BOT_API}/job/{uuid}").json()
    if job:
        if job.get("author") == ctx.author.id and job.get("status") == "rejected":
            u = requests.post(api, data={"status": "queued"}).json()
            if u["matched_count"] == 0:
                await ctx.respond(f"❌ Cannot retry {uuid}", ephemeral=True)
            else:
                await ctx.respond(f"💼 Job marked for retry.", ephemeral=True)
        else:
            await ctx.respond(f"❌ Cannot retry {uuid}", ephemeral=True)
    else:
        await ctx.respond(f"❌ Cannot find job `{uuid}`.  Check yourself.", ephemeral=True)


@bot.command(description="Retry a render request (intended for anims)")
async def sudo_retry(ctx, uuid):
    u = updateJob({"uuid": uuid, "status": "queued"})
    if u["matched_count"] == 0:
        await ctx.respond(f"❌ Cannot retry {uuid}", ephemeral=True)
    else:
        await ctx.respond(f"💼 Job marked for retry.", ephemeral=True)


@bot.command(description="Repeat a render request")
async def repeat(ctx, job_uuid, set_seed: discord.Option(int, "Seed", required=False, default=-1)):
    await ctx.respond("Repeat is obsolete.  Please use `/mutate`.", ephemeral=True)


@bot.command(description="Get details of a render request")
async def query(ctx, uuid):
    await ctx.respond(f"{BOT_API}/query/{uuid}")


@bot.command(description="Search by text")
async def search(ctx, regexp):
    await ctx.respond(f"{BOT_API}/search/{regexp}")


@bot.command(description="View first 5 rejects")
async def rejects(ctx):
    api = f"{BOT_API}/queue/rejected"
    await ctx.respond(api, ephemeral=True)


@bot.command(description="View your history")
async def myhistory(ctx):
    await ctx.respond(f"{BOT_PUBLIC_API}/myhistory/{ctx.author.id}", ephemeral=True)


async def agent_status():
    subject = requests.get(f"{BOT_API}/serverinfo/agentstats").json()
    if subject:
        channelid = int(subject["channel"])
        messageid = int(subject["message"])
    else:
        channelid = DISCORD_AGENT_STATS

    channel = bot.get_channel(channelid)
    table = Texttable(160)
    table.set_deco(Texttable.HEADER)
    # 't',  # text
    # 'f',  # float (decimal)
    # 'e',  # float (exponent)
    # 'i',  # integer
    # 'a'
    table.set_cols_dtype(["a", "a", "a", "a", "a", "a"])  # automatic
    # table.set_cols_align(["l", "r", "r", "r", "l"])
    data = []
    data.append(["Agent", "Last Seen", "Score", "Mode", "Model Config", "GPU Stats"])
    # await ctx.respond(f"""```\n{t}\n```""")
    api = f"{BOT_API}/agentstats"
    logger.info(f"🌍 Getting agent stats from '{api}'...")
    agents = requests.get(api).json()
    for a, agent in enumerate(agents):
        gpustats = agent.get("gpustats")
        if gpustats:
            gpustats = str(gpustats).replace("\n", "")
        last_seen = agent.get("last_seen")
        if last_seen:
            strdate = agent.get("last_seen")["$date"]
            try:
                last_seen = datetime.datetime.strptime(strdate, "%Y-%m-%dT%H:%M:%S.%fZ")
            except:
                last_seen = datetime.datetime.strptime(strdate, "%Y-%m-%dT%H:%M:%SZ")
            # last_seen = datetime.datetime.strptime(strdate,'%Y-%m-%dT%H:%M:%S.%fZ')
        data.append([agent.get("agent_id"), last_seen.strftime("%Y-%m-%d %H:%M:%S"), agent.get("score"), agent.get("mode"), agent.get("model_mode"), gpustats])

    table.add_rows(data)
    t = table.draw()
    embed = discord.Embed(
        title="Agent Status",
        description=f"The following GPUs are working:",
        color=discord.Colour.green(),
    )
    embed.add_field(name="Agents", value=f"```\n{t[:750]}\n```", inline=False)
    embed.set_footer(text=f"Last update: {datetime.datetime.now()}")
    if messageid != None:
        try:
            message = await channel.fetch_message(messageid)
            await message.edit(f"""```\n{t[:1900]}\n```""")
        except:
            logger.info(f"{messageid} not found.  Creating new one.")
            msg = await channel.send(f"""```\n{t[:1900]}\n```""")
            messageid = msg.id
            requests.post(f"{BOT_API}/serverinfo", headers={"x-dd-bot-token": BOT_TOKEN}, data={"subject": "agentstats", "channel": int(channel.id), "message": int(messageid)}).json()
    else:
        # await channel.send(embed = embed)
        msg = await channel.send(f"""```\n{t[:1900]}\n```""")
        messageid = msg.id
        requests.post(f"{BOT_API}/serverinfo", headers={"x-dd-bot-token": BOT_TOKEN}, data={"subject": "agentstats", "channel": int(channel.id), "message": int(messageid)}).json()


if __name__ == "__main__":
    print(discord.__version__)
    from discord.ext import tasks, commands

    bot.run(os.getenv("DISCORD_TOKEN"))
