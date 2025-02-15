import discord
from discord.ext import tasks
import os
import feedparser
import asyncio
from dotenv import load_dotenv

load_dotenv()

print('lancement du bot ...')

RSS_FEEDS = [
    'https://www.blogdumoderateur.com/feed/',
    'https://www.journaldugeek.com/feed/',
    'https://www.tomshardware.fr/feed/',
    'https://www.frandroid.com/feed/', 
    'https://korben.info/feed',
    'https://www.clubic.com/feed/rss'
]

CHANNEL_ID = None
CHECK_INTERVAL = 300
last_posts = {}

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.feed_task_started = False

    async def on_ready(self):
        print(f'Bot connecté en tant que {self.user}')
        global CHANNEL_ID
        CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
        
        channel = self.get_channel(CHANNEL_ID)
        if channel:
            print("Envoi des 3 derniers articles pour le test initial...")
            for feed_url in RSS_FEEDS:
                feed = feedparser.parse(feed_url)
                if feed.entries:
                    for entry in feed.entries[:3]:
                        await channel.send(entry.link)
                    last_posts[feed_url] = feed.entries[0].link

        if not self.feed_task_started:
            self.check_feeds_task.start()
            self.feed_task_started = True

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_feeds_task(self):
        if not CHANNEL_ID:
            return
            
        channel = self.get_channel(CHANNEL_ID)
        if channel:
            for feed_url in RSS_FEEDS:
                try:
                    feed = feedparser.parse(feed_url)
                    
                    # Vérifier si le flux a des entrées
                    if not feed.entries:
                        print(f"Flux vide ou inaccessible: {feed_url}")
                        continue
                        
                    if feed_url not in last_posts:
                        last_posts[feed_url] = feed.entries[0].link if feed.entries else None
                        continue

                    # Vérifier si nous avons un dernier article et s'il y a de nouveaux articles
                    if (last_posts[feed_url] and feed.entries and 
                        feed.entries[0].link != last_posts[feed_url]):
                        for entry in reversed(feed.entries):
                            if entry.link == last_posts[feed_url]:
                                break
                            await channel.send(entry.link)
                        last_posts[feed_url] = feed.entries[0].link

                except Exception as e:
                    print(f"Erreur avec le flux {feed_url}: {str(e)}")
                    continue

    @check_feeds_task.before_loop
    async def before_check_feeds(self):
        await self.wait_until_ready()

client = MyClient()
client.run(os.getenv('DISCORD_TOKEN'))