import discord, os, subprocess
from dotenv import load_dotenv
from pydotted import pydot
from loguru import logger
from profanity_check import predict, predict_prob
import joblib

load_dotenv()

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
    for job in arr:
        if job.author == ctx.author:
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
        arr.append(pydot({"text_prompt": text_prompt, "steps": steps, "author": ctx.author, "status": "queued"}))
        await ctx.respond(f"✅ Request added to list")
    else:
        await ctx.respond("\n".join(reasons))


# @bot.command()
# async def cmd(ctx, command: discord.Option(str, "Enter your command", required=False, default="ls -lart")):
#     arr.append(command)
#     res = subprocess.run(command.split(" "), stdout=subprocess.PIPE).stdout.decode("utf-8")
#     await ctx.respond(f"```\n{res}\n```")


@bot.command()
async def queue(ctx):
    # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
    embed = discord.Embed(
        title="Request Queue",
        description="The following requests are queued up.",
        color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
    )
    # https://www.markdownguide.org/tools/discord/
    md = f"""
    - some_request
      - some_prompts
      - steps
    """
    for j, job in enumerate(arr):
        embed.add_field(name=j, value=f"- Author: `{job.author}`\n - Text Prompt: `{job.text_prompt}`", inline=False)
    await ctx.respond(embed=embed)


@bot.command()
async def test(ctx):
    # https://docs.pycord.dev/en/master/api.html?highlight=embed#discord.Embed
    embed = discord.Embed(
        title="My Amazing Embed",
        description="Embeds are super easy, barely an inconvenience.",
        color=discord.Colour.blurple(),  # Pycord provides a class with default colors you can choose from
    )

    embed.add_field(name="A Normal Field", value="A really nice field with some information. **The description as well as the fields support markdown!**")

    embed.add_field(name="Inline Field 1", value="Inline Field 1", inline=True)
    embed.add_field(name="Inline Field 2", value="Inline Field 2", inline=True)
    embed.add_field(name="Inline Field 3", value="Inline Field 3", inline=True)

    embed.set_footer(text="Footer! No markdown here.")  # footers can have icons too
    embed.set_author(
        name="Fever Dream",
        icon_url="https://cdn.howles.cloud/icon.png",
    )
    # embed.set_thumbnail(url="https://example.com/link-to-my-thumbnail.png")
    # embed.set_image(url="https://example.com/link-to-my-banner.png")

    await ctx.respond("Hello! Here's a cool embed.", embed=embed)  # Send the embed with some text


class View(discord.ui.View):  # Create a class called View that subclasses discord.ui.View
    @discord.ui.button(label="Click me!", style=discord.ButtonStyle.primary)  # Create a button with the label "😎 Click me!" with color Blurple
    async def button_callback(self, button, interaction):
        await interaction.response.send_message("You clicked the button!")  # Send a message when the button is clicked


@bot.slash_command()  # Create a slash command
async def button(ctx):
    await ctx.respond("This is a button!", view=View())  # Send a message with our View class that contains the button


bot.run(os.getenv("DISCORD_TOKEN"))
