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

from db import get_database

warnings.filterwarnings("ignore")
from profanity_check import predict_prob

load_dotenv()

agents = ["mike"]
ticks = 0

async def queueBroadcast(who, status, author=None, channel = None, messageid=None):
    with get_database() as client:
        q = {"status": {"$nin": ["archived","rejected"]}}
        if who == "me":
            q ["author"] = int(author)
        if status != "all":
            q["status"] = status
        if status == "all" and who=="me":
            del q["status"]

        query = {"$query": q, "$orderby": {"timestamp": -1}}
        queue = client.database.get_collection("queue").find(query).limit(10)
        channel = discord.utils.get(bot.get_all_channels(), name=channel)
        color = discord.Colour.blurple()
        if status == "processing":
            color = discord.Colour.green()

        embed = discord.Embed(
            title="Request Queue",
            description=f"The following requests are {status}",
            color=color,  # Pycord provides a class with default colors you can choose from
        )
        for j, job in enumerate(queue):
            user = await bot.fetch_user(job.get("author"))
            summary = f"""
            - 🧑‍🦲 Author: <@{job.get('author')}>
            - ✍️ Text Prompt: `{job.get('text_prompt')}`
            - Mode: `{job.get('mode')}`
            - Status: `{job.get('status')}`
            - Progress: `{job.get('percent')}%`
            - Timestamp: `{job.get('timestamp')}`
            - Agent: `{job.get('agent_id')}`
            """
            embed.add_field(name=job.get("uuid"), value=summary, inline=False)
        if messageid != None:
            message = await channel.fetch_message(messageid)
            await message.edit(embed = embed)
        else:
            await channel.send(embed = embed)


# this code will be executed every 10 seconds after the bot is ready
@tasks.loop(seconds=10)
async def task_loop():
    global ticks
    ticks += 1
    image_channels = ["images-discussion", "images"]
    dream_channels = ["day-dreams"]
    botspam_channels = ["botspam"]
    logger.info("loop")
    with get_database() as client:
        logger.info("Updating Active Queue")
        await queueBroadcast("all", "processing", None, "active-jobs", 981572405468209162)
        await queueBroadcast("all", "queued", None, "waiting-jobs", 981582971477848084)
        # Process any Events
        logger.info("checking events")
        eventCollection = client.database.get_collection("events")
        events = eventCollection.find({"$query": {"ack": {"$eq": False}}})
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
            if event_type == "progress":
                job_uuid = event.get("event")["job_uuid"]
                embed, file, view = retrieve(job_uuid)
                if embed:
                    # logger.info(f"Progress Update found for {job_uuid}")
                    jobCollection = client.database.get_collection("queue")
                    job = jobCollection.find_one({"$query": {"uuid": job_uuid}})
                    last_preview = job.get("last_preview")
                    toosoon = False
                    if last_preview == None:
                        toosoon = False
                    else:
                        n = datetime.datetime.now()
                        duration = n - last_preview
                        if duration.total_seconds() < 20:
                            logger.info(duration)
                            toosoon = True
                    if job:
                        if job.get("progress_msg") and job.get('status') == 'processing' and toosoon == False:
                            render_type = job.get('render_type')
                            if render_type is None:
                                render_type = "render"

                            if render_type == "sketch":
                                channel = "sketches"
                            if render_type == "render":
                                channel = "images"
                            channel = discord.utils.get(bot.get_all_channels(), name=channel)
                            # logger.info(f"Updating message {job.get('progress_msg')}...")
                            try:
                                message = await channel.fetch_message(job.get("progress_msg"))
                                if file:
                                    await message.edit(file = file, view = view, embed = embed)
                                else:
                                    await message.edit(embed = embed, view = view)
                            except:
                                pass
                                # logger.error(f"Could not update message {job.get('progress_msg')}")
                            jobCollection.update_one({"uuid": job_uuid},{"$set": {"last_preview": datetime.datetime.now()}})
                        # else:
                            # logger.info(f"Progress update received but no message to update {job_uuid}")
            
                d = eventCollection.delete_one({"uuid": event.get("uuid")})
                logger.info(f"Deleted {d.deleted_count} processed event(s).")
            # eventCollection.update_one({"uuid": event.get("uuid")}, {"$set": {"ack": True}})
        
        # Display any new messages
        logger.info("checking messages")
        messageCollection = client.database.get_collection("logs")
        messages = messageCollection.find({"$query": {"ack": {"$ne": True}}})
        for message in messages:
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

            messageCollection.update_one({"uuid": message.get("uuid")}, {"$set": {"ack": True}})
        
        # Display any completed jobs
        
        logger.info("checking completed jobs")
        query = {"status": "complete"}
        queueCollection = client.database.get_collection("queue")
        completed = queueCollection.count_documents(query)
        if completed == 0:
            logger.info("No completed jobs.")
        else:
            completedJob = queueCollection.find_one(query)
            logger.info(f"Found completed job: Mode: {completedJob.get('mode')}")
            
            render_type = completedJob.get('render_type')
            if render_type is None:
                render_type = "render"

            if render_type == "sketch":
                channel = "sketches"
            if render_type == "render":
                channel = "images"

            if completedJob.get("mode") != "dream":
                channels = ["images-discussion", channel]
            else:
                channels = dream_channels
            

            for channel in channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                embed, file, view = retrieve(completedJob.get('uuid'))
                try:
                    if completedJob.get("progress_msg"):
                        try:
                            message = await channel.fetch_message(completedJob.get("progress_msg"))
                        except:
                            message = None
                        if message:
                            await message.edit(view=view, file=file)
                            await message.edit(embed=embed)
                        else:
                            await channel.send(embed=embed, view=view, file=file)
                    else:
                        await channel.send(embed=embed, view=view, file=file)
                except Exception as e:
                    tb = traceback.format_exc()
                    await channel.send(f"💀 Cannot display {completedJob.get('uuid')}\n`{tb}`")
            queueCollection.update_one({"uuid": completedJob.get("uuid")}, {"$set": {"status": "archived"}})

        # Display any failed jobs
        
        logger.info("checking failed jobs")
        query = {"status": "failed"}
        queueCollection = client.database.get_collection("queue")
        completed = queueCollection.count_documents(query)
        if completed == 0:
            logger.info("No failures found.")
        else:
            completedJob = queueCollection.find_one(query)
            for channel in botspam_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                embed = discord.Embed(
                    title="Ah shit.",
                    description=f"Job `{completedJob.get('uuid')}` failed, <@{completedJob.get('author')}>!  Blame `{completedJob.get('agent_id')}`",
                    color=discord.Colour.blurple(),
                )
                # embed, file, view = retrieve(completedJob.get('uuid'))
                await channel.send(embed=embed)
            queueCollection.update_one({"uuid": completedJob.get("uuid")}, {"$set": {"status": "rejected"}})

bot = discord.Bot(debug_guilds=[945459234194219029])  # specify the guild IDs in debug_guilds
arr = []
agents = []
STEP_LIMIT = int(os.getenv("STEP_LIMIT", 150))
PROFANITY_THRESHOLD = float(os.getenv("PROFANITY_THRESHOLD", 0.7))
AUTHOR_LIMIT = int(os.getenv("AUTHOR_LIMIT", 2))

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

@bot.slash_command(name="display")
async def display(ctx, job_uuid):
    embed, file, view = retrieve(job_uuid)
    try:
        await ctx.respond(embed=embed, view=view, file=file)
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
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        completedJob = queueCollection.find_one({"uuid": uuid})
        embed = discord.Embed(
            description=f"Attached is the GPU run log for you, nerd:\n`{uuid}`",
            color=discord.Colour.blurple(),
        )
        view = discord.ui.View()
        if completedJob.get('log'):
            file = discord.File(f"images/{completedJob.get('log')}", filename=completedJob.get("log"))
        else:
            file = None
        # embed.set_image(url=f"attachment://{completedJob.get('log')}")
        return embed, file, view

def retrieve(uuid):
    logger.info(f"Retrieving {uuid}")
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        completedJob = queueCollection.find_one({"uuid": uuid})
        if not completedJob:
            return None, None, None
        try:
            duration = completedJob.get("duration")
            if duration == None:
                duration = 0
        except:
            duration = 0

        preview = completedJob.get("preview")
        status = completedJob.get("status")
        percent = completedJob.get("percent")
        
        color = discord.Colour.blurple()
        if percent == None:
            percent = 0
        if status == "archived" or status=="complete":
            color = discord.Colour.green()
        if status == "processing":
            color = discord.Colour.green()
        if status == "queued":
            color = discord.Colour.blurple()
        logger.info(f"{uuid} - {status}")
        embed = discord.Embed(
            description=f"Author: <@{completedJob.get('author')}>\n`{completedJob.get('uuid')}`\nStatus: `{status}`",
            color=color,
            fields= [
                discord.EmbedField("Text Prompt", f"`{completedJob.get('text_prompt')}`", inline=False),
                discord.EmbedField("Steps", f"`{completedJob.get('steps')}`", inline=True),
                discord.EmbedField("Model", f"`{completedJob.get('model')}`", inline=True),
                discord.EmbedField("Shape", f"`{completedJob.get('shape')}`", inline=True),
                discord.EmbedField("Inner Cut Power", f"`{completedJob.get('cut_ic_pow')}`", inline=True),
                discord.EmbedField("Saturation Scale", f"`{completedJob.get('sat_scale')}`", inline=True),
                discord.EmbedField("CLIP Guidance Scale", f"`{completedJob.get('clip_guidance_scale')}`", inline=True),
                discord.EmbedField("Clamp Max", f"`{str(completedJob.get('clamp_max'))}`", inline=True),
                discord.EmbedField("Seed", f"`{str(completedJob.get('set_seed'))}`", inline=True),
                discord.EmbedField("Symmetry", f"`{str(completedJob.get('symmetry'))}`", inline=True),
                discord.EmbedField("Symmetry Loss Scale", f"`{str(completedJob.get('symmetry_loss_scale'))}`", inline=True),
                discord.EmbedField("Duration (sec)", f"`{str(math.floor(duration))}`", inline=True),
                discord.EmbedField("Progress", f"`{str(percent)}%`", inline=True)
            ]
        )
        embed.set_author(
            name="Fever Dream",
            icon_url="https://cdn.howles.cloud/feverdream.png",
        )

        view = discord.ui.View()

        async def detCallback(interaction):
            # await interaction.response.edit_message(content="💖", view=view)
            with get_database() as client:
                result = client.database.get_collection("queue").find_one({"uuid": interaction.custom_id})
                embed = discord.Embed(
                    title=f"Job {completedJob.get('uuid')} Details",
                    description=completedJob.get("text_prompt"),
                    color=discord.Colour.blurple(),
                    fields= [
                        discord.EmbedField("Text Prompt", completedJob.get("text_prompt"), inline=True),
                        # discord.EmbedField("Model", completedJob.get("model"), inline=True),
                        # discord.EmbedField("Shape", completedJob.get("shape"), inline=True),
                        # discord.EmbedField("Inner Cut Power", completedJob.get("cut_ic_pow"), inline=True),
                        # discord.EmbedField("Saturation Scale", completedJob.get("sat_scale"), inline=True),
                        # discord.EmbedField("CLIP Guidance Scale", completedJob.get("clip_guidance_scale"), inline=True)
                    ]
                )
                embed.set_author(
                    name=f"Fever Dreams"
                )
                await interaction.response.send_message(embed=embed, delete_after=60)

        detButton = discord.ui.Button(label="Details", style=discord.ButtonStyle.green, emoji="🔎", custom_id=completedJob.get('uuid'))
        detButton.callback = detCallback
        # hateButton = discord.ui.Button(label="Hate it", style=discord.ButtonStyle.danger, emoji="😢")
        # hateButton.callback = hateCallback
        # view.add_item(detButton)
        # view.add_item(hateButton)
        preview = completedJob.get("preview")
        logger.info(preview)
        fn = ""
        if preview == True:
            fn =f"{uuid}_progress.png"
        if status == "archived" or status=="complete":
            fn =completedJob.get("filename")
        if fn != "":
            file = discord.File(f"images/{fn}", fn)
            embed.set_image(url=f"attachment://{fn}")
        else:
            file = None
    return embed, file, view

@bot.slash_command(name="modaltest")
async def modal_slash(ctx):
    """Shows an example of a modal dialog being invoked from a slash command."""
    modal = MyModal(title="Slash Command Modal")
    await ctx.send_modal(modal)

@bot.command(description="Please HALP")
async def help(ctx, term: discord.Option(str, "Term", required=False, default="help", choices=[
        discord.OptionChoice("Text Prompts", value="text_prompts"),
        discord.OptionChoice("Steps", value="steps"),
        discord.OptionChoice("CLIP Guidance Scale", value="clip_guidance_scale"),
        discord.OptionChoice("Inner Cut Power", value="cut_ic_pow"),
        discord.OptionChoice("Clamp Max", value="clamp_max"),
        discord.OptionChoice("Seed", value="set_seed")
    ])):
    help = ""
    if(term == "clamp_max"):
        help = """
        Sets the value of the clamp_grad limitation. Default is 0.05, providing for smoother, more muted coloration in images, but setting higher values `(0.15-0.3)` can provide interesting contrast and vibrancy.
        """
    if(term == "text_prompts"):
        help = """
        Phrase, sentence, or string of words and phrases describing what the image should look like.  The words will be analyzed by the AI and will guide the diffusion process toward the image(s) you describe. These can include commas and weights to adjust the relative importance of each element.  E.g. "A beautiful painting of a singular lighthouse, shining its light across a tumultuous sea of blood by greg rutkowski and thomas kinkade, Trending on artstation."
        """
    if(term == "cut_ic_pow"):
        help = """
        This sets the size of the border used for inner cuts.  High cut_ic_pow values have larger borders, and therefore the cuts themselves will be smaller and provide finer details.  If you have too many or too-small inner cuts, you may lose overall image coherency and/or it may cause an undesirable 'mosaic' effect.   Low cut_ic_pow values will allow the inner cuts to be larger, helping image coherency while still helping with some details.
        """
    if(term == "steps"):
        help = """
        When creating an image, the denoising curve is subdivided into steps for processing. Each step (or iteration) involves the AI looking at subsets of the image called "cuts" and calculating the "direction" the image should be guided to be more like the prompt. Then it adjusts the image with the help of the diffusion denoiser, and moves to the next step.

        Increasing steps will provide more opportunities for the AI to adjust the image, and each adjustment will be smaller, and thus will yield a more precise, detailed image. Increasing steps comes at the expense of longer render times. Also, while increasing steps should generally increase image quality, there is a diminishing return on additional steps beyond 250 - 500 steps. However, some intricate images can take 1000, 2000, or more steps. It is really up to the user.
        """
    if(term == "help"):
        help = "Yo dog, I heard you needed help so I put help in your help."

    if(term == "clip_guidance_scale"):
        help=f"""
        CGS is one of the most important parameters you will use. It tells DD how strongly you want CLIP to move toward your prompt each timestep.  Higher is generally better, but if CGS is too strong it will overshoot the goal and distort the image. So a happy medium is needed, and it takes experience to learn how to adjust CGS. 
 
        Note that this parameter generally scales with image dimensions. In other words, if you increase your total dimensions by `50%` (e.g. a change from `512 x 512` to `512 x 768`), then to maintain the same effect on the image, you’d want to increase `clip_guidance_scale` from `5000` to `7500`.
        """
    embed = discord.Embed(title=f"{term}", color=discord.Color.random(), description = help)
    await ctx.respond(embed=embed)
@bot.command(description="Sends the bot's latency.")  # this decorator makes a slash command
async def ping(ctx):  # a slash command will be created with the name "ping"
    await ctx.respond(f"Pong! Latency is {bot.latency}")


@bot.event
async def on_ready():
    logger.info(f"{bot.user} is ready and online!")
    task_loop.start()  # important to start the loop


@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server, {member.mention}! Enjoy your stay here.")

async def placeholder(ctx, job_uuid):
    logger.info(f"Placeholder called {job_uuid}")
    channel = discord.utils.get(bot.get_all_channels(), name="images")
    embed = discord.Embed(
        title="Request Queued",
        description=f"📃 {ctx.author.mention} Your request has been queued up.\nJob: `{job_uuid}`",
        color=discord.Colour.blurple(),
    )
    msg = await channel.send(embed=embed)
    
    with get_database() as client:
        client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"progress_msg": msg.id}})

async def do_render(ctx, render_type, text_prompt, steps, shape, model, clip_guidance_scale, cut_ic_pow, sat_scale, clamp_max, set_seed, symmetry, symmetry_loss_scale):
    reject = False
    reasons = []
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        query = {"author": int(ctx.author.id), "status": {"$nin": ["archived","rejected"]}}
        jobCount = queueCollection.count_documents(query)
        if jobCount >= AUTHOR_LIMIT:
            reject = True
            reasons.append(f"- ❌ You have too many jobs queued (`{jobCount}`).  Wait until your queued job count is under {AUTHOR_LIMIT} or remove an existing with /remove command.")

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
            text_prompt = text_prompt.replace("“", '"')
            text_prompt = text_prompt.replace("”", '"')
            record = {
                "uuid": job_uuid, 
                "mode": "userwork",
                "render_type": render_type,
                "text_prompt": text_prompt, 
                "steps": steps, 
                "shape": shape, 
                "model": model,
                "symmetry": symmetry,
                "symmetry_loss_scale": symmetry_loss_scale,
                "clip_guidance_scale": clip_guidance_scale,
                "clamp_max" : clamp_max,
                "set_seed" : set_seed,
                "cut_ic_pow": cut_ic_pow,
                "sat_scale": sat_scale,
                "author": int(ctx.author.id),
                "status": "queued",
                "timestamp": datetime.datetime.utcnow()}
            queueCollection = client.database.get_collection("queue")
            queueCollection.insert_one(record)
            # await placeholder(ctx, job_uuid)
            embed, file, view = retrieve(job_uuid)
            if render_type is None:
                render_type = "render"

            if render_type == "sketch":
                channel = "sketches"
            if render_type == "render":
                channel = "images"

            channel = discord.utils.get(bot.get_all_channels(), name=channel)
            msg = await channel.send(embed=embed, view=view)
            with get_database() as client:
                client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"progress_msg": msg.id}})

            # botspam_channels = ["botspam"]
            # for channel in botspam_channels:
            #     channel = discord.utils.get(bot.get_all_channels(), name=channel)
            #     embed = discord.Embed(
            #         title="Request Queued",
            #         description=f"📃 <@{ctx.author.id}> Your request has been queued up.\nJob: `{job_uuid}`",
            #         color=discord.Colour.blurple(),
            #     )
            #     msg = await channel.send(embed=embed)
            await ctx.respond("Command Accepted.",delete_after=3)

    else:
        await ctx.respond("\n".join(reasons))


@bot.command(description="Submit a Disco Diffusion Render Request")
async def render(
    ctx,
    text_prompt: discord.Option(str, "Enter your text prompt", required=True, default = "A beautiful painting of a singular lighthouse, shining its light across a tumultuous sea of blood by greg rutkowski and thomas kinkade, Trending on artstation."),
    steps: discord.Option(int, "Number of steps", required=False, default=150),
    shape: discord.Option(str, "Image Shape", required=False, default="landscape", choices=[
        discord.OptionChoice("Landscape", value="landscape"),
        discord.OptionChoice("Portrait", value="portrait"),
        discord.OptionChoice("Square", value="square"),
        discord.OptionChoice("Panoramic", value="pano")
    ]),
    model: discord.Option(str, "Models", required=False, default="default", choices=[
        discord.OptionChoice("Default (ViTB16+32, RN50)", value="default"),
        discord.OptionChoice("ViTB16+32, RN50x64", value="rn50x64"),
        discord.OptionChoice("ViTB16+32, ViTL14", value="vitl14"),
        discord.OptionChoice("ViTB16+32, ViTL14x336", value="vitl14x336"),
    ]),
    clip_guidance_scale: discord.Option(int, "CLIP guidance scale", required=False, default=5000),
    cut_ic_pow: discord.Option(int, "CLIP Innercut Power", required=False, default=1),
    sat_scale: discord.Option(int, "Saturation Scale", required=False, default=0),
    clamp_max: discord.Option(str, "Clamp Max", required=False, default="0.05"),
    set_seed: discord.Option(int, "Seed", required=False, default=-1),
    symmetry: discord.Option(str, "Symmetry", required=False, default="no", choices=[
        discord.OptionChoice("No", value="no"),
        discord.OptionChoice("Yes", value="yes"),
    ]),
    symmetry_loss_scale: discord.Option(int, "Symmetry Loss Scale", required=False, default=1500),
):
    await do_render(ctx, "render", text_prompt, steps, shape, model, clip_guidance_scale, cut_ic_pow, sat_scale, clamp_max, set_seed, symmetry, symmetry_loss_scale)

@bot.command(description="Submit a Disco Diffusion Sketch Request (will jump queue)")
async def sketch(
    ctx,
    text_prompt: discord.Option(str, "Enter your text prompt", required=True, default = "A beautiful painting of a singular lighthouse, shining its light across a tumultuous sea of blood by greg rutkowski and thomas kinkade, Trending on artstation."),
    shape: discord.Option(str, "Image Shape", required=False, default="landscape", choices=[
        discord.OptionChoice("Landscape", value="landscape"),
        discord.OptionChoice("Portrait", value="portrait"),
        discord.OptionChoice("Square", value="square"),
        discord.OptionChoice("Panoramic", value="pano")
    ]),
    clip_guidance_scale: discord.Option(int, "CLIP guidance scale", required=False, default=5000),
    cut_ic_pow: discord.Option(int, "CLIP Innercut Power", required=False, default=1),
    sat_scale: discord.Option(int, "Saturation Scale", required=False, default=0),
    clamp_max: discord.Option(str, "Clamp Max", required=False, default="0.05"),
    set_seed: discord.Option(int, "Seed", required=False, default=-1),
    symmetry: discord.Option(str, "Symmetry", required=False, default="no", choices=[
        discord.OptionChoice("No", value="no"),
        discord.OptionChoice("Yes", value="yes"),
    ]),
    symmetry_loss_scale: discord.Option(int, "Symmetry Loss Scale", required=False, default=1500),
):
    await do_render(ctx, "sketch", text_prompt, 50, shape, "default", clip_guidance_scale, cut_ic_pow, sat_scale, clamp_max, set_seed, symmetry, symmetry_loss_scale)

# @bot.command(description="Nuke Render Queue (debug)")
# async def nuke(ctx):
#     with get_database() as client:
#         result = client.database.get_collection("queue").delete_many({"status": {"$nin": ["archived","rejected"]}})
#     await ctx.respond(f"✅ Queue nuked.")


@bot.command(description="Remove a render request (intended for admins)")
async def destroy(ctx, uuid):
    with get_database() as client:
        result = client.database.get_collection("queue").find_one({"uuid": uuid})
        if result:
            if result.get('progress_msg'):
                render_type = result.get('render_type')
                if render_type is None:
                    render_type = "render"

                if render_type == "sketch":
                    channel = "sketches"
                if render_type == "render":
                    channel = "images"
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                msg = await channel.fetch_message(result.get('progress_msg'))
                logger.info(f"{msg.id} deleted.")
                await msg.delete()

            result = client.database.get_collection("queue").delete_many({"uuid": uuid})
            count = result.deleted_count

            if count == 0:
                await ctx.respond(f"❌ Could not delete job `{uuid}`.  Check the Job ID.")
            else:
                await ctx.respond(f"🗑️ Job destroyed.")
        else:
            await ctx.respond(f"❌ Could not find job `{uuid}`.  Check the Job ID.")

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

@bot.command(description="Retry a render request (intended for anims)")
async def sudo_retry(ctx, uuid):
    with get_database() as client:
        result = client.database.get_collection("queue").update_one({"uuid": uuid}, {"$set": {"status": "queued"}})
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
        result["timestamp"] = datetime.datetime.utcnow()
        result["author"] = int(ctx.author.id)
        result["percent"] = 0
        result["preview"] = False
        result["progress_msg"] = None
        result["duration"] = 0
        result["mode"] = 'repeat'
        render_type = result["render_type"]
        result = client.database.get_collection("queue").insert_one(result)
        insertID = result
        botspam_channels = ["botspam"]
        if not insertID:
            for channel in botspam_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                embed = discord.Embed(
                    title="Error",
                    description=f"❌ <@{ctx.author.id}> Cannot repeat `{job_uuid}`",
                    color=discord.Colour.blurple(),
                )
                await channel.send(embed=embed)
                await ctx.respond("Command Accepted.",delete_after=3)
        else:
            
            if render_type is None:
                render_type = "render"

            if render_type == "sketch":
                channel = "sketches"
            if render_type == "render":
                channel = "images"
                
            embed, file, view = retrieve(new_uuid)
            channel = discord.utils.get(bot.get_all_channels(), name=channel)
            msg = await channel.send(embed=embed, view=view)
            with get_database() as client:
                client.database.get_collection("queue").update_one({"uuid": new_uuid}, {"$set": {"progress_msg": msg.id}})

            await ctx.respond("Command Accepted.",delete_after=3)

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

@bot.command(description="View first 5 rejects")
async def rejects(ctx):
    with get_database() as client:
        queue = client.database.get_collection("queue").find({"$query": {"status": "rejected"}, "$orderby": {"timestamp": -1}}).limit(5)
        botspam_channels = ["botspam"]
        # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
        for channel in botspam_channels:
            channel = discord.utils.get(bot.get_all_channels(), name=channel)
            embed = discord.Embed(
                title="Reject Queue",
                description="The following requests bugged out.",
                color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
            )
            for j, job in enumerate(queue):
                user = await bot.fetch_user(job.get("author"))
                summary = f"""
                - 🧑‍🦲 Author: <@{job.get('author')}>
                - ✍️ Text Prompt: `{job.get('text_prompt')}`
                - 🤖 Model: `{job.get('model')}`
                - ⌚ Timestamp: `{job.get('timestamp')}`
                - 🖥️ Agent: `{job.get('agent_id')}`
                """
                embed.add_field(name=job.get("uuid"), value=summary, inline=False)
            await channel.send(embed=embed)
        await ctx.respond("Command Accepted.",delete_after=3)


@bot.command(description="View next 10 render queue entries")
async def queue(ctx):
    await query_queue(ctx, who = "all", status = "all")

@bot.command(description="View active queue entries")
async def active(ctx):
    await query_queue(ctx, who = "all", status = "processing")


async def query_queue(ctx, who, status):
    with get_database() as client:
        q = {"status": {"$nin": ["archived","rejected"]}}
        if who == "me":
            q ["author"] = int(ctx.author.id)
        if status != "all":
            q["status"] = status
        if status == "all" and who=="me":
            del q["status"]

        query = {"$query": q, "$orderby": {"timestamp": -1}}
        queue = client.database.get_collection("queue").find(query).limit(10)
        botspam_channels = ["botspam"]
        for channel in botspam_channels:
            channel = discord.utils.get(bot.get_all_channels(), name=channel)
            # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
            color = discord.Colour.blurple()
            if status == "processing":
                color = discord.Colour.green()

            embed = discord.Embed(
                title="Request Queue",
                description="The following requests are queued up.",
                color=color,  # Pycord provides a class with default colors you can choose from
            )
            for j, job in enumerate(queue):
                user = await bot.fetch_user(job.get("author"))
                summary = f"""
                - 🧑‍🦲 Author: <@{job.get('author')}>
                - ✍️ Text Prompt: `{job.get('text_prompt')}`
                - Mode: `{job.get('mode')}`
                - Status: `{job.get('status')}`
                - Progress: `{job.get('percent')}%`
                - Timestamp: `{job.get('timestamp')}`
                - Agent: `{job.get('agent_id')}`
                """
                embed.add_field(name=job.get("uuid"), value=summary, inline=False)
            await channel.send(embed=embed)
        await ctx.respond("Command Accepted.",delete_after=3)

@bot.command(description="View your history")
async def myhistory(ctx):
    await query_queue(ctx, who = "me", status = "all")

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
            embed.add_field(name=agent.get("agent_id"), value=f"""
            - Last Seen: `{agent.get('last_seen')}`
            - Score: `{agent.get('score')}`
            - Idle Time: `{agent.get('idle_time')} sec`
            - Mode: `{agent.get('mode')}`
            """, inline=False)
        await ctx.respond(embed=embed)


if __name__ == "__main__":
    print(discord.__version__)
    from discord.ext import tasks, commands

    bot.run(os.getenv("DISCORD_TOKEN"))
