#!/usr/bin/env python3
"""
Social Media Monitor for Gatlin - Enhanced Version
Checks for new posts across multiple platforms and posts to Discord webhook
"""

import json
import os
import logging
import requests
import certifi
from datetime import datetime
from typing import Dict, Optional, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
import re
import time
import random
import ssl
import urllib3
from rich.logging import RichHandler
from dotenv import load_dotenv
import sys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, handlers=[RichHandler()], format='%(message)s')
logger = logging.getLogger("rich")

load_dotenv()

CACHE_FILE = "cache.json"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_LOG_WEBHOOK_URL = os.getenv("DISCORD_LOG_WEBHOOK_URL")
DISCORD_USER_ID = os.getenv("DISCORD_USER_ID")

class SocialMonitor:
    def __init__(self):
        self.cache = self.load_cache()
        
    def load_cache(self) -> Dict[str, str]:
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def save_cache(self):
        with open(CACHE_FILE, 'w') as f:
            json.dump(self.cache, f, indent=2)
    
    def send_discord_webhook(self, content: str, embed: Optional[Dict] = None, log: bool = False, mention_on_error: bool = False):
        webhook_url = DISCORD_LOG_WEBHOOK_URL if log else DISCORD_WEBHOOK_URL
        if not webhook_url:
            logger.error("discord webhook url not configured")
            return False
        if mention_on_error and DISCORD_USER_ID:
            content = f"<@{DISCORD_USER_ID}> {content}"
        payload = {"content": content}
        if embed:
            payload["embeds"] = [embed]
        logger.info(f"sending discord webhook to: {webhook_url}")
        logger.info(f"payload: {payload}")
        try:
            response = requests.post(webhook_url, json=payload, timeout=30)
            response.raise_for_status()
            logger.info("discord message sent successfully!")
            return True
        except Exception as e:
            logger.error(f"failed to send discord webhook: {e}")
            return False
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10), retry=retry_if_exception_type((requests.RequestException, requests.Timeout)))
    def _make_request(self, url: str, headers: Dict[str, str], timeout: int = 30) -> requests.Response:
        """Make HTTP request with retry logic"""
        response = requests.get(url, headers=headers, timeout=timeout, verify=False)
        response.raise_for_status()
        return response
    
    def check_youtube(self) -> bool:
        logger.info("checking youtube for new content...")
        try:
            return self._check_youtube_impl()
        except Exception as e:
            logger.error(f"youtube check failed: {e}")
            return False
    
    def _check_youtube_impl(self) -> bool:
        import googleapiclient.discovery
        
        api_key = os.getenv("YOUTUBE_API_KEY")
        if not api_key:
            logger.error("youtube api key not configured")
            return False
        
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)
        
        try:
            channel_id = "UCs_d8-5LTWCRtsuWsfscBWg"
            logger.info(f"using channel id: {channel_id}")
            
            search_response = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                maxResults=1,
                order="date",
                type="video"
            ).execute()
            
            if not search_response.get("items"):
                logger.info("no youtube videos found")
                return False
            
            latest_video = search_response["items"][0]
            video_id = latest_video["id"]["videoId"]
            
            cache_key = "youtube_last_video"
            if self.cache.get(cache_key) == video_id:
                video_date = latest_video['snippet']['publishedAt'][:10]
                logger.info(f"nothing new on youtube. latest video: {latest_video['snippet']['title']} ({video_id})")
                logger.info(f"published: {video_date}")
                logger.info(f"description: {latest_video['snippet']['description'][:150]}...")
                return False
            
            video_details = youtube.videos().list(
                part="snippet,statistics",
                id=video_id
            ).execute()
            
            if not video_details.get("items"):
                return False
            
            video = video_details["items"][0]
            title = video["snippet"]["title"]
            description = video["snippet"]["description"]
            thumbnail = video["snippet"]["thumbnails"]["high"]["url"]
            video_url = f"https://youtu.be/{video_id}"
            view_count = video.get("statistics", {}).get("viewCount", "0")
            
            embed = {
                "title": title,
                "url": video_url,
                "color": 16711680,
                "image": {"url": thumbnail},
                "description": description[:200] + "..." if len(description) > 200 else description,
                "fields": [{"name": "Views", "value": f"{int(view_count):,}", "inline": True}]
            }
            
            content = f"new video on youtube! \n\"{title}\"\n{video_url}"
            
            if self.send_discord_webhook(content, embed):
                self.cache[cache_key] = video_id
                logger.info(f"posted new youtube video: {title}")
                return True
            
        except Exception as e:
            logger.error(f"youtube api error: {e}")
            return False
        
        return False
    
    def check_instagram(self) -> bool:
        logger.info("checking instagram for new content...")
        methods = [self._check_instagram_web, self._check_instagram_rss]
        
        for method in methods:
            try:
                result = method()
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"instagram method {method.__name__} failed: {e}")
                continue
        
        logger.error("all instagram scraping methods failed")
        return False
    
    def _check_instagram_web(self) -> Optional[bool]:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'X-Requested-With': 'XMLHttpRequest'
            }
            
            time.sleep(random.uniform(3, 7))
            
            url = "https://www.instagram.com/api/v1/users/web_profile_info/?username=gatlin"
            headers['X-IG-App-ID'] = '936619743392459'
            
            try:
                response = self._make_request(url, headers, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    return self._process_instagram_json(data)
            except Exception as e:
                logger.warning(f"instagram json api failed: {e}")
            
            del headers['X-IG-App-ID']
            url = "https://www.instagram.com/gatlin/"
            response = self._make_request(url, headers, timeout=15)
            
            return self._process_instagram_html(response.text)
            
        except Exception as e:
            logger.error(f"instagram web scraping error: {type(e).__name__}: {str(e)}")
            return None
    
    def _check_instagram_rss(self) -> Optional[bool]:
        """Try alternative Instagram RSS/feed endpoints"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            url = "https://www.picuki.com/profile/gatlin"
            response = self._make_request(url, headers, timeout=15)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            post_links = soup.find_all('a', href=re.compile(r'/media/\d+'))
            if post_links:
                href = post_links[0].get('href', '')
                post_id_match = re.search(r'/media/(\d+)', href)
                if post_id_match:
                    post_id = post_id_match.group(1)
                    
                    cache_key = "instagram_last_post"
                    if self.cache.get(cache_key) == post_id:
                        logger.info(f"nothing new on instagram. latest post: {post_id}")
                        return False
                    
                    post_img = soup.find('img', src=re.compile(r'https://.*\.jpg'))
                    image_url = post_img['src'] if post_img else None
                    
                    embed = {
                        "title": "Instagram Post",
                        "url": f"https://www.instagram.com/p/{post_id}/",
                        "color": 14315734,
                        "description": "New Instagram post from gatlin",
                        "author": {
                            "name": "gatlin",
                            "url": "https://www.instagram.com/gatlin/"
                        }
                    }
                    
                    if image_url:
                        embed["image"] = {"url": image_url}
                    
                    content = f"new post on instagram!\nhttps://www.instagram.com/p/{post_id}/"
                    
                    if self.send_discord_webhook(content, embed):
                        self.cache[cache_key] = post_id
                        logger.info(f"posted new instagram post: {post_id}")
                        return True
            
            return None
            
        except Exception as e:
            logger.error(f"Instagram RSS method error: {e}")
            return None
    
    def _process_instagram_json(self, data: Dict) -> Optional[bool]:
        try:
            user_data = data.get('data', {}).get('user', {})
            if not user_data:
                return None
            
            posts = user_data.get('edge_owner_to_timeline_media', {}).get('edges', [])
            if not posts:
                logger.info("No Instagram posts found in JSON data")
                return None
            
            latest_post = posts[0]['node']
            return self._process_instagram_post(latest_post)
            
        except Exception as e:
            logger.error(f"Instagram JSON processing error: {e}")
            return None
    
    def _process_instagram_html(self, html: str) -> Optional[bool]:
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            script_tags = soup.find_all('script')
            
            for script in script_tags:
                if script.string and 'edge_owner_to_timeline_media' in script.string:
                    json_match = re.search(r'window\._sharedData = ({.*?});', script.string)
                    if json_match:
                        try:
                            shared_data = json.loads(json_match.group(1))
                            posts = shared_data.get('entry_data', {}).get('ProfilePage', [{}])[0].get('graphql', {}).get('user', {}).get('edge_owner_to_timeline_media', {}).get('edges', [])
                            if posts:
                                return self._process_instagram_post(posts[0]['node'])
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
            
            post_links = soup.find_all('a', href=re.compile(r'/p/[A-Za-z0-9_-]+/'))
            if post_links:
                href = post_links[0].get('href', '')
                shortcode_match = re.search(r'/p/([A-Za-z0-9_-]+)/', href)
                if shortcode_match:
                    post_id = shortcode_match.group(1)
                    return self._process_instagram_post({'shortcode': post_id})
            
            return None
            
        except Exception as e:
            logger.error(f"Instagram HTML processing error: {e}")
            return None
    
    def _process_instagram_post(self, post_data: Dict) -> bool:
        try:
            post_id = post_data.get('shortcode', '')
            if not post_id:
                logger.warning("Could not extract Instagram post ID")
                return False
            
            cache_key = "instagram_last_post"
            if self.cache.get(cache_key) == post_id:
                post_type = "reel" if post_data.get('is_video', False) else "post"
                post_date = 'Unknown date'
                if post_data.get('taken_at_timestamp'):
                    post_date = datetime.fromtimestamp(post_data['taken_at_timestamp']).strftime('%Y-%m-%d %H:%M')
                
                logger.info(f"No new Instagram content - latest {post_type}: {post_id} ({post_date})")
                
                if 'edge_media_to_caption' in post_data:
                    captions = post_data.get('edge_media_to_caption', {}).get('edges', [])
                    if captions:
                        caption = captions[0].get('node', {}).get('text', '')[:150]
                        logger.info(f"Caption: {caption}{'...' if len(caption) == 150 else ''}")
                elif post_data.get('accessibility_caption'):
                    logger.info(f"Alt text: {post_data.get('accessibility_caption')[:150]}")
                
                return False
            
            caption = ''
            is_video = post_data.get('is_video', False)
            image_url = post_data.get('display_url')
            like_count = post_data.get('edge_media_preview_like', {}).get('count', 0)
            
            if 'edge_media_to_caption' in post_data:
                captions = post_data.get('edge_media_to_caption', {}).get('edges', [])
                if captions:
                    caption = captions[0].get('node', {}).get('text', '')
            
            post_type = "reel" if is_video else "post"
            post_url = f"https://www.instagram.com/p/{post_id}/"
            
            embed = {
                "title": f"Instagram {post_type.title()}",
                "url": post_url,
                "color": 14315734,
                "description": (caption[:300] + "...") if len(caption) > 300 else (caption or "New Instagram post"),
                "author": {
                    "name": "gatlin",
                    "url": "https://www.instagram.com/gatlin/"
                }
            }
            
            if image_url:
                embed["image"] = {"url": image_url}
            
            content = f"new {post_type} on instagram!\n{post_url}"
            
            if self.send_discord_webhook(content, embed):
                self.cache[cache_key] = post_id
                logger.info(f"posted new instagram {post_type}: {post_id}")
                return True
                
        except Exception as e:
            logger.error(f"instagram post processing error: {type(e).__name__}: {str(e)}")
            return False
        
        return False
    
    def run_all_checks(self):
        logger.info("starting social media monitoring...")

        platforms = [
            ("YouTube", self.check_youtube),
            ("Instagram", self.check_instagram)
        ]

        results = {}
        errors = {}

        for platform_name, check_func in platforms:
            try:
                result = check_func()
                results[platform_name] = "✓ success" if result else "- no new content"
            except Exception as e:
                results[platform_name] = "✗ failed"
                errors[platform_name] = str(e)
                logger.error(f"failed to check {platform_name}: {e}")
                self.send_discord_webhook(f"error in {platform_name}: {e}", log=True, mention_on_error=True)

        logger.info("")
        logger.info("social media monitoring completed")
        logger.info("results summary:")
        for platform, status in results.items():
            logger.info(f"  {platform}: {status}")
        self.save_cache()

        is_github = os.getenv("GITHUB_ACTIONS") == "true"
        run_type = "automatic (github actions)" if is_github else "manual (local)"
        summary_lines = ["**gattycord monitor run summary**", f"run type: {run_type}", ""]
        summary_lines.append("results:")
        for platform, status in results.items():
            summary_lines.append(f"> {platform.lower()}: {status}")
        if errors:
            summary_lines.append("")
            summary_lines.append("errors:")
            for platform, err in errors.items():
                summary_lines.append(f"> {platform.lower()}: {err}")
        if DISCORD_USER_ID:
            summary_lines.append(f"<@{DISCORD_USER_ID}>")
        summary = "\n".join(summary_lines)
        self.send_discord_webhook(summary, log=True)

if __name__ == "__main__":
    monitor = SocialMonitor()
    monitor.run_all_checks()