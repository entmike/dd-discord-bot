import datetime
from random import choices
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

# this code will be executed every 10 seconds after the bot is ready
@tasks.loop(seconds=10)
async def task_loop():
    global ticks
    ticks += 1
    image_channels = ["images-discussion", "images"]
    botspam_channels = ["botspam"]
    with get_database() as client:

        # Process any Events

        eventCollection = client.database.get_collection("events")
        events = eventCollection.find({"$query": {"ack": {"$ne": True}}})
        for event in events:
            title = "Message"
            embed = discord.Embed(
                title="Event",
                description=event.get("event"),
                color=discord.Colour.blurple(),
            )
            for channel in botspam_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                # await channel.send(embed=embed)
            
            eventCollection.update_one({"uuid": event.get("uuid")}, {"$set": {"ack": True}})

        
        # Display any new messages

        messageCollection = client.database.get_collection("logs")
        messages = messageCollection.find({"$query": {"ack": {"$ne": True}}})
        for message in messages:
            title = "Message"
            if message.get("title"):
                title = message.get(title)
            embed = discord.Embed(
                title=title,
                description=message.get("message"),
                color=discord.Colour.blurple(),
            )
            for channel in botspam_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                await channel.send(embed=embed)
                
            messageCollection.update_one({"uuid": message.get("uuid")}, {"$set": {"ack": True}})
        
        # Display any completed jobs
        
        query = {"status": "complete"}
        queueCollection = client.database.get_collection("queue")
        completed = queueCollection.count_documents(query)
        if completed == 0:
            logger.info("No completed jobs.")
        else:
            completedJob = queueCollection.find_one(query)
            for channel in image_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                embed, file, view = retrieve(completedJob.get('uuid'))
                await channel.send(embed=embed, view=view, file=file)
            queueCollection.update_one({"uuid": completedJob.get("uuid")}, {"$set": {"status": "archived"}})

        # Display any failed jobs
        
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
        # self.add_item(
        #     discord.ui.Select(
        #         placeholder="landscape",
        #         custom_id="shape",
        #         options = [
        #             discord.SelectOption(
        #                 label = "Landscape",
        #                 value = "landscape"
        #             ),discord.SelectOption(
        #                 label = "Portrait",
        #                 value = "portrait"
        #             )
        #         ]
        #     )
        # )
        # self.add_item(
        #     discord.ui.Select(
        #         placeholder="model",
        #         custom_id="model",
        #         options = [
        #             discord.SelectOption(
        #                 label = "Default (ViTB16+32, RN50)",
        #                 value = "default"
        #             ),discord.SelectOption(
        #                 label = "ViTL16+32, RN50x64",
        #                 value = "rn50x64"
        #             )
        #         ]
        #     )
        # )
   
    # clip_guidance_scale: discord.Option(int, "CLIP guidance scale", required=False, default=1500),
    # cut_ic_pow: discord.Option(int, "CLIP Innercut Power", required=False, default=1),





    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Your Modal Results", color=discord.Color.random())
        embed.add_field(name="First Input", value=self.children[0].value, inline=False)
        embed.add_field(name="Second Input", value=self.children[1].value, inline=False)
        await interaction.response.send_message(embeds=[embed])

@bot.slash_command(name="display")
async def display(ctx, job_uuid):
    embed, file, view = retrieve(job_uuid)
    await ctx.respond(embed=embed, file=file, view=view)

@bot.slash_command(name="logs")
async def display(ctx, job_uuid):
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
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        completedJob = queueCollection.find_one({"uuid": uuid})
        embed = discord.Embed(
            description=f"Completed render <@{completedJob.get('author')}>\n`{completedJob.get('uuid')}`",
            color=discord.Colour.blurple(),
            fields= [
                discord.EmbedField("Text Prompt", completedJob.get("text_prompt"), inline=True),
                discord.EmbedField("Steps", completedJob.get("steps"), inline=True),
                discord.EmbedField("Model", completedJob.get("model"), inline=True),
                discord.EmbedField("Shape", completedJob.get("shape"), inline=True),
                discord.EmbedField("Inner Cut Power", completedJob.get("cut_ic_pow"), inline=True),
                discord.EmbedField("CLIP Guidance Scale", completedJob.get("clip_guidance_scale"), inline=True),
                discord.EmbedField("Clamp Max", str(completedJob.get("clamp_max")), inline=True)
            ]
        )
        embed.set_author(
            name="Fever Dream",
            icon_url="https://cdn.howles.cloud/Butthead.png",
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
                    discord.EmbedField("Model", completedJob.get("model"), inline=True),
                    discord.EmbedField("Shape", completedJob.get("shape"), inline=True),
                    discord.EmbedField("Inner Cut Power", completedJob.get("cut_ic_pow"), inline=True),
                    discord.EmbedField("CLIP Guidance Scale", completedJob.get("clip_guidance_scale"), inline=True)
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
    file = discord.File(f"images/{completedJob.get('filename')}", filename=completedJob.get("filename"))
    embed.set_image(url=f"attachment://{completedJob.get('filename')}")
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
        discord.OptionChoice("Clamp Max", value="clamp_max")
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
    text_prompt: discord.Option(str, "Enter your text prompt", required=True, default = "A beautiful painting of a singular lighthouse, shining its light across a tumultuous sea of blood by greg rutkowski and thomas kinkade, Trending on artstation."),
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
    clip_guidance_scale: discord.Option(int, "CLIP guidance scale", required=False, default=5000),
    cut_ic_pow: discord.Option(int, "CLIP Innercut Power", required=False, default=1),
    clamp_max: discord.Option(str, "Clamp Max", required=False, default="0.05"),
):
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
            text_prompt = text_prompt.replace(':','')
            record = {
                "uuid": job_uuid, 
                "text_prompt": text_prompt, 
                "steps": steps, 
                "shape": shape, 
                "model": model,
                "clip_guidance_scale": clip_guidance_scale,
                "clamp_max" : clamp_max,
                "cut_ic_pow": cut_ic_pow,
                "author": int(ctx.author.id),
                "status": "queued",
                "timestamp": datetime.datetime.utcnow()}
            queueCollection = client.database.get_collection("queue")
            queueCollection.insert_one(record)
            botspam_channels = ["botspam"]
            for channel in botspam_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                embed = discord.Embed(
                    title="Request Queued",
                    description=f"📃 <@{ctx.author.id}> Your request has been queued up.\nJob: `{job_uuid}`",
                    color=discord.Colour.blurple(),
                )
                await channel.send(embed=embed)
                await ctx.respond("Command Accepted.",delete_after=3)

    else:
        await ctx.respond("\n".join(reasons))

@bot.command(description="Nuke Render Queue (debug)")
async def nuke(ctx):
    with get_database() as client:
        result = client.database.get_collection("queue").delete_many({"status": {"$nin": ["archived","rejected"]}})
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
        result["author"] = int(ctx.author.id)
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
            for channel in botspam_channels:
                channel = discord.utils.get(bot.get_all_channels(), name=channel)
                embed = discord.Embed(
                    title="Job Repeated",
                    description=f"💼 <@{ctx.author.id}> Job `{job_uuid}` marked for a repeat run.  New uuid: `{new_uuid}`",
                    color=discord.Colour.blurple(),
                )
                await channel.send(embed=embed)
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


@bot.command(description="View next 5 render queue entries")
async def queue(ctx):
    with get_database() as client:
        queue = client.database.get_collection("queue").find({"$query": {"status": {"$nin": ["archived","rejected"]}}, "$orderby": {"timestamp": -1}}).limit(5)
        botspam_channels = ["botspam"]
        for channel in botspam_channels:
            channel = discord.utils.get(bot.get_all_channels(), name=channel)
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
                - Progress: `{job.get('percent')}%`
                - Timestamp: `{job.get('timestamp')}`
                - Agent: `{job.get('agent_id')}`
                """
                embed.add_field(name=job.get("uuid"), value=summary, inline=False)
            await channel.send(embed=embed)
        await ctx.respond("Command Accepted.",delete_after=3)


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
            embed.add_field(name=agent.get("agent_id"), value=f"- Last Seen: `{agent.get('last_seen')}`\n- Score: `{agent.get('score')}`", inline=False)
        await ctx.respond(embed=embed)


if __name__ == "__main__":
    print(discord.__version__)
    from discord.ext import tasks, commands

    bot.run(os.getenv("DISCORD_TOKEN"))
