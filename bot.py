import discord
from discord import app_commands
from discord.ext import tasks
import os
import feedparser
import asyncio
import ssl
import urllib.request
from dotenv import load_dotenv
from time import sleep
from collections import defaultdict

load_dotenv()

print('lancement du bot ...')

# Configuration SSL et User-Agent
ssl._create_default_https_context = ssl._create_unverified_context
feedparser.USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

RSS_FEEDS = [
    'https://www.blogdumoderateur.com/feed/',
    'https://www.journaldugeek.com/feed/',
    'https://www.tomshardware.fr/feed/',
    'https://www.frandroid.com/feed',  
    'https://korben.info/feed',
    'https://www.clubic.com/feed/rss',
    'https://www.numerama.com/feed/',
    'https://www.01net.com/feed/',
]

CHECK_INTERVAL = 120  # Vérifier les flux toutes les 120 secondes
last_posts = {}

# Dictionnaire des catégories tech courantes et leurs alias
TECH_CATEGORIES = {
    'tech': ['technologie', 'technology', 'tech', 'high-tech'],
    'ia': ['intelligence artificielle', 'ai', 'artificial intelligence', 'ia'],
    'dev': ['développement', 'development', 'programming', 'code'],
    'security': ['sécurité', 'security', 'cybersecurity', 'cybersécurité'],
    'gaming': ['jeux vidéo', 'gaming', 'games', 'jeu'],
    'news': ['actualités', 'news', 'actu'],
    'mobile': ['smartphone', 'android', 'ios', 'mobile'],
    'hardware': ['matériel', 'hardware', 'composants']
}

class MyClient(discord.Client):
    def __init__(self):
        # Mise à jour des intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True  # Ajout de l'intent guilds
        
        super().__init__(intents=intents, application_id=os.getenv('APPLICATION_ID'))
        self.feed_task_started = False
        self.tree = app_commands.CommandTree(self)
        self.categories = defaultdict(set)
        self.user_preferences = defaultdict(list)
        self.active_users = set()
        
        # Ajouter toutes les commandes au démarrage
        self.setup_commands()

    def setup_commands(self):
        """Enregistre manuellement toutes les commandes"""
        print("Configuration des commandes...")
        
        @self.tree.command(name="start", description="Démarrer la réception des actualités")
        async def start(interaction: discord.Interaction):
            await self.start_news(interaction)

        @self.tree.command(name="stop", description="Arrêter la réception des actualités")
        async def stop(interaction: discord.Interaction):
            await self.stop_news(interaction)

        @self.tree.command(name="categories", description="Voir les catégories disponibles")
        async def categories(interaction: discord.Interaction):
            await self.show_categories(interaction)

        @self.tree.command(name="follow", description="Suivre une catégorie")
        @app_commands.describe(category="La catégorie à suivre")
        async def follow(interaction: discord.Interaction, category: str):
            await self.follow_category(interaction, category)

        @self.tree.command(name="unfollow", description="Ne plus suivre une catégorie")
        @app_commands.describe(category="La catégorie à ne plus suivre")
        async def unfollow(interaction: discord.Interaction, category: str):
            await self.unfollow_category(interaction, category)

        @self.tree.command(name="myprefs", description="Voir vos préférences")
        async def myprefs(interaction: discord.Interaction):
            await self.show_preferences(interaction)

        @self.tree.command(name="clear", description="Effacer vos préférences")
        async def clear(interaction: discord.Interaction):
            await self.clear_preferences(interaction)

        print("✓ Commandes configurées")

    async def setup_hook(self):
        try:
            print("Tentative de synchronisation des commandes...")
            # Synchronisation forcée pour tous les serveurs
            await self.tree.sync()
            print("✓ Synchronisation globale effectuée")
            
            # Vérification des commandes
            commands = await self.tree.fetch_commands()
            print(f"✓ Commandes disponibles: {len(commands)} commandes")
            for cmd in commands:
                print(f"  - /{cmd.name}")
        except Exception as e:
            print(f"✗ Erreur lors de la synchronisation: {str(e)}")

    async def analyze_feed_categories(self, feed):
        """Analyse et extrait les catégories d'un flux"""
        categories = set()
        for entry in feed.entries:
            if hasattr(entry, 'tags'):
                for tag in entry.tags:
                    categories.add(tag.term.lower())
            if hasattr(entry, 'category'):
                if isinstance(entry.category, list):
                    categories.update(cat.lower() for cat in entry.category)
                else:
                    categories.add(entry.category.lower())
        return categories

    async def on_ready(self):
        print(f'=== BOT DÉMARRÉ ===')
        print(f'Nom du bot: {self.user}')
        print(f'ID du bot: {self.user.id}')
        
        print("\n=== INITIALISATION DES FLUX RSS ===")
        for feed_url in RSS_FEEDS:
            try:
                print(f'\nTentative d\'initialisation de {feed_url}')
                feed = feedparser.parse(feed_url)
                if feed.entries:
                    last_posts[feed_url] = feed.entries[0].link
                    print(f'✓ Flux initialisé avec succès')
                    print(f'  → Dernier article: {feed.entries[0].title}')
                else:
                    print(f'⚠ Flux vide pour {feed_url}')
            except Exception as e:
                print(f'✗ ERREUR d\'initialisation: {str(e)}')

        if not self.feed_task_started:
            self.check_feeds_task.start()
            self.feed_task_started = True
            print(f'\n=== SURVEILLANCE DES FLUX DÉMARRÉE ===')
            print(f'Intervalle de vérification: {CHECK_INTERVAL} secondes')

        # Ajout de l'analyse des catégories
        print("\n=== ANALYSE DES CATÉGORIES ===")
        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                if feed.entries:
                    cats = await self.analyze_feed_categories(feed)
                    self.categories[feed_url] = cats
                    print(f"\nCatégories trouvées pour {feed_url}:")
                    for cat in sorted(cats):
                        print(f"  - {cat}")
            except Exception as e:
                print(f"Erreur d'analyse des catégories: {str(e)}")

    async def fetch_feed(self, feed_url, max_retries=3):
        print(f'\nRécupération du flux: {feed_url}')
        for attempt in range(max_retries):
            try:
                # Configuration pour suivre les redirections
                feed = feedparser.parse(feed_url, handlers=[urllib.request.HTTPRedirectHandler()])
                
                # Vérification du statut et gestion des redirections
                if hasattr(feed, 'status'):
                    if feed.status in [200, 301, 302, 307, 308]:  # Codes de succès et redirection
                        if feed.entries:
                            print(f'✓ Flux récupéré avec succès')
                            return feed
                        else:
                            print(f'⚠ Flux récupéré mais vide')
                    else:
                        print(f'⚠ Statut HTTP: {feed.status}')
                else:
                    if feed.entries:
                        print(f'✓ Flux récupéré avec succès')
                        return feed
                    print('⚠ Pas de statut HTTP disponible')
                    
            except Exception as e:
                print(f'Tentative {attempt + 1}/{max_retries} échouée: {str(e)}')
                if attempt == max_retries - 1:
                    print(f'✗ Échec final après {max_retries} tentatives')
                    return None
                await asyncio.sleep(2)
        return None

    async def on_message(self, message):
        # Ignorer les messages du bot
        if message.author == self.user:
            return

        # Ne répondre qu'aux messages privés
        if not isinstance(message.channel, discord.DMChannel):
            return

        # Si c'est la première fois que l'utilisateur envoie un message en MP
        if str(message.author.id) not in self.active_users:
            await message.channel.send("""
👋 Bonjour! Je suis votre assistant d'actualités tech.
Voici les commandes disponibles:
`/start` - Démarrer la réception des actualités
`/stop` - Arrêter la réception
`/categories` - Voir les catégories disponibles
`/follow <catégorie>` - Suivre une catégorie
`/unfollow <catégorie>` - Ne plus suivre une catégorie
`/myprefs` - Voir vos préférences
`/clear` - Effacer vos préférences
""")

    @app_commands.command(name="start", description="Démarrer la réception des actualités")
    async def start_news(self, interaction: discord.Interaction):
        try:
            # Ouvrir un MP avec l'utilisateur
            dm_channel = await interaction.user.create_dm()
            user_id = str(interaction.user.id)
            self.active_users.add(user_id)
            
            # Répondre dans le serveur
            await interaction.response.send_message("✅ Je vous ai envoyé un message privé!", ephemeral=True)
            
            # Envoyer le message de bienvenue en MP
            await dm_channel.send("""
👋 Bonjour! Je suis votre assistant d'actualités tech.
Vous recevrez désormais les actualités ici.

Voici les commandes disponibles:
`/categories` - Voir les catégories disponibles
`/follow <catégorie>` - Suivre une catégorie
`/unfollow <catégorie>` - Ne plus suivre une catégorie
`/myprefs` - Voir vos préférences
`/clear` - Effacer vos préférences
`/stop` - Arrêter la réception
""")
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ Je ne peux pas vous envoyer de messages privés. Veuillez autoriser les messages privés dans vos paramètres Discord.", ephemeral=True)

    async def command_check(self, interaction: discord.Interaction):
        """Vérifie si l'utilisateur est actif et peut utiliser les commandes"""
        user_id = str(interaction.user.id)
        if user_id not in self.active_users:
            await interaction.response.send_message("⚠️ Vous devez d'abord utiliser `/start` pour activer le service!", ephemeral=True)
            return False
        return True

    @app_commands.command(name="categories", description="Affiche toutes les catégories disponibles")
    async def show_categories(self, interaction: discord.Interaction):
        if not await self.command_check(interaction):
            return
        all_categories = set()
        for cats in self.categories.values():
            all_categories.update(cats)
        
        response = "**Catégories disponibles:**\n"
        for cat in sorted(all_categories):
            matching_tech = [k for k, v in TECH_CATEGORIES.items() if cat in v]
            if matching_tech:
                response += f"- {cat} (alias: {matching_tech[0]})\n"
            else:
                response += f"- {cat}\n"
        
        await interaction.response.send_message(response)

    @app_commands.command(name="follow", description="Suivre une catégorie spécifique")
    async def follow_category(self, interaction: discord.Interaction, category: str):
        if not await self.command_check(interaction):
            return
        category = category.lower()
        user_id = str(interaction.user.id)
        
        # Vérifier si la catégorie existe
        found = False
        for cats in self.categories.values():
            if category in cats or any(category in v for v in TECH_CATEGORIES.values()):
                found = True
                break
        
        if found:
            if category not in self.user_preferences[user_id]:
                self.user_preferences[user_id].append(category)
                await interaction.response.send_message(f"Vous suivez maintenant la catégorie: {category}")
            else:
                await interaction.response.send_message("Vous suivez déjà cette catégorie!")
        else:
            await interaction.response.send_message("Catégorie non trouvée!")

    @app_commands.command(name="stop", description="Arrêter la réception des actualités")
    async def stop_news(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        if user_id in self.active_users:
            self.active_users.discard(user_id)
            self.user_preferences[user_id].clear()
            await interaction.response.send_message("✅ Vous ne recevrez plus d'actualités.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Vous n'étiez pas inscrit aux actualités.", ephemeral=True)

    @app_commands.command(name="help", description="Affiche l'aide des commandes")
    async def show_help(self, interaction: discord.Interaction):
        if not await self.command_check(interaction):
            return
        help_text = """
**Commandes disponibles:**
`/start` - Démarrer la réception des actualités en MP
`/stop` - Arrêter la réception des actualités
`/categories` - Voir toutes les catégories disponibles
`/follow <catégorie>` - Suivre une catégorie
`/unfollow <catégorie>` - Ne plus suivre une catégorie
`/myprefs` - Voir vos préférences actuelles
`/clear` - Effacer toutes vos préférences
"""
        await interaction.response.send_message(help_text)

    @app_commands.command(name="myprefs", description="Voir vos préférences actuelles")
    async def show_preferences(self, interaction: discord.Interaction):
        if not await self.command_check(interaction):
            return
        user_id = str(interaction.user.id)
        if user_id in self.active_users:
            prefs = self.user_preferences[user_id]
            if prefs:
                response = "**Vos catégories suivies:**\n" + "\n".join(f"- {cat}" for cat in prefs)
            else:
                response = "Vous ne suivez aucune catégorie spécifique (vous recevez toutes les actualités)"
        else:
            response = "Vous n'êtes pas inscrit aux actualités. Utilisez /start pour commencer."
        await interaction.response.send_message(response)

    @app_commands.command(name="unfollow", description="Ne plus suivre une catégorie")
    async def unfollow_category(self, interaction: discord.Interaction, category: str):
        if not await self.command_check(interaction):
            return
        user_id = str(interaction.user.id)
        if category in self.user_preferences[user_id]:
            self.user_preferences[user_id].remove(category)
            await interaction.response.send_message(f"Vous ne suivez plus la catégorie: {category}")
        else:
            await interaction.response.send_message("Vous ne suiviez pas cette catégorie.")

    @app_commands.command(name="clear", description="Effacer toutes vos préférences")
    async def clear_preferences(self, interaction: discord.Interaction):
        if not await self.command_check(interaction):
            return
        user_id = str(interaction.user.id)
        self.user_preferences[user_id].clear()
        await interaction.response.send_message("Toutes vos préférences ont été effacées. Vous recevrez toutes les actualités.")

    async def should_send_article(self, entry, user_id):
        """Vérifie si un article correspond aux préférences de l'utilisateur"""
        if not self.user_preferences[user_id]:  # Si pas de préférences, tout envoyer
            return True
            
        entry_categories = set()
        if hasattr(entry, 'tags'):
            entry_categories.update(tag.term.lower() for tag in entry.tags)
        if hasattr(entry, 'category'):
            if isinstance(entry.category, list):
                entry_categories.update(cat.lower() for cat in entry.category)
            else:
                entry_categories.add(entry.category.lower())
                
        # Vérifier les correspondances avec les préférences
        for pref in self.user_preferences[user_id]:
            if pref in entry_categories:
                return True
            # Vérifier les alias tech
            for tech_cats in TECH_CATEGORIES.values():
                if pref in tech_cats and any(cat in tech_cats for cat in entry_categories):
                    return True
        return False

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_feeds_task(self):
        print('\n=== VÉRIFICATION DES FLUX ===')
        if not self.active_users:
            return

        for feed_url in RSS_FEEDS:
            try:
                print(f'\nTraitement de {feed_url}')
                feed = await self.fetch_feed(feed_url)
                
                if not feed or not feed.entries:
                    print('⚠ Flux vide ou inaccessible')
                    continue
                    
                if feed_url not in last_posts:
                    last_posts[feed_url] = feed.entries[0].link
                    print('Premier traitement du flux, enregistrement du dernier article')
                    continue

                if feed.entries[0].link != last_posts[feed_url]:
                    print('→ Nouveaux articles détectés!')
                    new_articles = []
                    for entry in feed.entries:
                        if entry.link == last_posts[feed_url]:
                            break
                        new_articles.append((entry, entry.link))
                        print(f'  → Nouvel article trouvé: {entry.title}')
                    
                    print(f'Envoi de {len(new_articles)} nouveaux articles...')
                    for entry, article_link in reversed(new_articles):
                        for user_id in self.active_users:
                            try:
                                if await self.should_send_article(entry, user_id):
                                    user = await self.fetch_user(int(user_id))
                                    if user:
                                        await user.send(f"🔥 Nouvel article pour vous :\n{article_link}")
                                        print(f'✓ Article envoyé à l\'utilisateur {user_id}')
                            except Exception as e:
                                print(f'✗ Erreur d\'envoi: {str(e)}')
                        await asyncio.sleep(1)

                    last_posts[feed_url] = feed.entries[0].link
                    print('✓ Mise à jour du dernier article enregistré')
                else:
                    print('→ Aucun nouvel article')

            except Exception as e:
                print(f'✗ ERREUR générale: {str(e)}')
                continue

    @check_feeds_task.before_loop
    async def before_check_feeds(self):
        await self.wait_until_ready()

if __name__ == "__main__":
    client = MyClient()
    print("Démarrage du bot...")
    client.run(os.getenv('DISCORD_TOKEN'))