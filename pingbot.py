import datetime
import json
import re
import sqlite3

import discord

# https://discordapp.com/api/oauth2/authorize?client_id=194989427573915658&permissions=19456&scope=bot

settings_file = "pingme.json"

cmd_prefix = "pingme"
user_pings_per_server = 5
bot_ops = []
database_file = "./pingme.db"


class PingBot(discord.Client):
    def __init__(self, **options):
        super().__init__(**options)
        self.db = sqlite3.connect(database_file)
        try:
            # self.db.execute("DROP TABLE IF EXISTS pings;")
            self.db.execute(
                "CREATE TABLE pings(id LONG NOT NULL PRIMARY KEY, guild LONG NOT NULL, channel LONG NOT NULL, user LONG NOT NULL, regex TEXT NOT NULL, date TEXT NOT NULL, num INT NOT NULL);")
        except sqlite3.OperationalError:
            print("Table already exists in database")

        row = self.db.execute("SELECT id FROM pings ORDER BY id DESC;").fetchone()
        if row:
            self.id_index = row[0]
        else:
            self.id_index = 0
        print("Highest existing id:", self.id_index)

    async def on_ready(self):
        print("Ready")
        await self.change_presence(activity=discord.Game("pingme help"))

    def prune_database(self):
        for row in self.db.execute("SELECT DISTINCT guild FROM pings;").fetchall():
            found = False
            for guild in self.guilds:
                if guild.id == row[0]:
                    found = True
                    break
            if not found:
                self.db.execute("DELETE FROM pings WHERE guild=?;", (row[0],))
                self.db.commit()
        for row in self.db.execute("SELECT DISTINCT channel, guild FROM pings;").fetchall():
            guild = None
            for g in self.guilds:
                if g.id == row[1]:
                    guild = g
                    break
            if guild and row[0] != 0:
                found = False
                for channel in g.channels:
                    if channel.id == row[0]:
                        found = True
                        break
                if not found:
                    self.db.execute("DELETE FROM pings WHERE guild=? AND channel=?;", (row[1], row[0]))
                    self.db.commit()

    async def handle_command(self, message, cmd):
        if message.author.id in bot_ops:
            if cmd.lower().startswith(("shutdown", "exit", "kill")):
                await message.channel.send("Shutting down...")
                await self.logout()
            elif cmd.lower().startswith("prune"):
                await message.channel.send("Pruning database...")
                self.prune_database()
                await message.channel.send("Finished pruning database!")

            elif cmd.lower().startswith("restart"):
                await message.channel.send("Unimplemented feature")

        if cmd.lower().startswith("help"):
            await message.channel.send("""A bot that will ping you when messages are sent that match a given phrase
```Commands/Usage:
pingme help                     - Shows this message
pingme                          - PMs you a list of your ping rules
pingme list                     - PMs you a list of your ping rules
pingme add [WORD/PHRASE]        - Adds a new server-wide ping rule
pingme addhere [WORD/PHRASE]    - Adds a new channel-specific rule
pingme regex [REGEX]            - Adds a new server-wide regex rule
pingme regexhere [REGEX]        - Adds a new channel-specific regex rule
pingme delete [ID]              - Deletes a rule with the given ID (found in the rule list)
pingme remove [ID]              - Deletes a rule with the given ID (found in the rule list)```""")
        elif cmd.lower().startswith(("list", "rules", "notifications", "pings")):
            await self.send_pingme_list(message)
        elif cmd.lower().startswith(("remove", "delete")):
            try:
                id = int(cmd[6:])
                row = self.db.execute("SELECT user, regex FROM pings WHERE id=?;", (id,)).fetchone()
                if row:
                    if row[0] == message.author.id:
                        self.db.execute("DELETE FROM pings WHERE id=?", (id,))
                        self.db.commit()
                        await message.channel.send("Deleted rule: '" + row[1] + "'")
                    else:
                        await message.channel.send("Cannot delete someone else's rule")
                else:
                    await message.channel.send("ID: " + str(id) + " does not exist")
            except:
                await message.channel.send(cmd[6:] + " is not a number")
        elif cmd.lower().startswith("add "):
            await self.new_ping(message, "/" + cmd[4:] + "/i")
        elif cmd.lower().startswith("addhere "):
            await self.new_ping(message, "/" + cmd[8:] + "/i", True)
        elif cmd.lower().startswith("regex "):
            await self.new_ping(message, cmd[6:])
        elif cmd.lower().startswith("regexhere "):
            await self.new_ping(message, cmd[10:], True)

    async def new_ping(self, message, regex, channel_specific=False):
        count = self.db.execute("SELECT COUNT(*) FROM pings WHERE guild=? AND user=?",
                                (message.guild.id, message.author.id)).fetchone()[0]
        if count >= user_pings_per_server:
            await message.channel.send(
                "Limit of " + str(user_pings_per_server) + " ping rules reached. Delete a rule to make room.")
        else:
            channel = 0
            channel_name = "All"
            if channel_specific:
                channel = message.channel.id
                channel_name = message.channel.name
            self.db_new_ping(message.guild.id, channel, message.author.id, regex)
            await message.channel.send(
                "New rule added in `" + message.guild.name + "`/`" + channel_name + "` - Rule: `" + regex + "`")

    def db_new_ping(self, guild, channel, user, regex):
        self.id_index += 1
        self.db.execute("INSERT INTO pings VALUES(?, ?, ?, ?, ?, ?, 0);",
                        (self.id_index, guild, channel, user, regex, str(datetime.datetime.utcnow())))
        self.db.commit()

    def db_increment_ping(self, ping_id):
        self.db.execute("UPDATE pings SET num = num + 1 WHERE id = ?;", (ping_id,))
        self.db.commit()

    async def send_pingme_list(self, message):
        result = "Ping rules:"
        for row in self.db.execute("SELECT * FROM pings WHERE user=?;", (message.author.id,)).fetchall():
            guild = self.get_guild(row[1])
            channel = guild.get_channel(row[2])
            if channel:
                channel = channel.name
            else:
                channel = "All"
            result += "\n[ID: " + str(row[0]) + "] (Pings: " + str(
                row[6]) + ")         `" + guild.name + "`/`" + channel + "`         Rule: `" + row[
                          4] + "`         Added: " + row[5]
        if not message.author.dm_channel:
            await message.author.create_dm()
        await message.author.dm_channel.send(result)

    async def on_message(self, message):
        if message.author == self.user:
            return

        if isinstance(message.channel, discord.TextChannel):
            rows = self.db.execute(
                "SELECT id, regex, user FROM pings WHERE guild=? AND (channel=0 OR channel=?);",
                (message.guild.id, message.channel.id)).fetchall()
            for row in rows:
                if re.fullmatch("^/.*/i$", row[1]):
                    search = re.search(row[1][1:-2], message.content, re.IGNORECASE)
                else:
                    search = re.search(row[1], message.content)
                if search:
                    user = self.get_user(row[2])
                    if user:
                        self.db_increment_ping(row[0])
                        if not user.dm_channel:
                            await user.create_dm()
                        await user.dm_channel.send(
                            "A ping you set up triggered on this message:\n\"" + message.guild.name + "\"/\"" +
                            message.channel.name + "\"\n" + message.author.mention + ": \"" + message.content +
                            "\"\nJump to message: " + message.jump_url)

        if message.content.lower().startswith(cmd_prefix):
            if len(message.content) == len(cmd_prefix):
                await self.send_pingme_list(message)
            else:
                cmd = message.content[len(cmd_prefix) + 1:].strip()
                if len(cmd) > 0:
                    await self.handle_command(message, cmd)


if __name__ == "__main__":
    try:
        with open(settings_file, 'r') as infile:
            j = json.load(infile)

            user_pings_per_server = j['user_pings_per_server']
            print("user_pings_per_server:", user_pings_per_server)
            database_file = j['database_file']
            print("database_file:", database_file)
            for op in j['bot_ops']:
                bot_ops.append(op)
            print("bot_ops:", str(bot_ops))

            bot = PingBot()
            bot.run(j['token'])
    except FileNotFoundError:
        print("No settings file found, creating dummy file")
        with open(settings_file, 'w') as outfile:
            json.dump(
                {'token': 'YOUR BOT TOKEN HERE', 'user_pings_per_server': user_pings_per_server, 'bot_ops': bot_ops,
                 'database_file': database_file}, outfile)
