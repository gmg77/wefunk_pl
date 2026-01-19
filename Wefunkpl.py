import requests
from bs4 import BeautifulSoup
import json
import time
import random
import re
from datetime import datetime

# --- Configuration ---
BASE_URL = "https://www.wefunkradio.com/show/{}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def clean_text(text):
    if text:
        return " ".join(text.split())
    return ""

def format_date_string(date_str):
    """
    Parses a date string (typically YYYY-MM-DD) and returns it 
    in 'Month DD, YYYY' format (e.g., 'December 05, 2025').
    """
    if not date_str or date_str == "Unknown":
        return date_str
        
    try:
        # Try parsing standard ISO format YYYY-MM-DD (common in filenames and database text)
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%B %d, %Y")
    except ValueError:
        # If it's already in another format or fails to parse, return it as-is
        return date_str

def parse_show(show_id):
    url = BASE_URL.format(show_id)
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        # 1. Hard Check: HTTP Status Code
        if response.status_code == 404:
            print(f"xx Show {show_id} not found (404 Error)")
            return None
        elif response.status_code != 200:
            print(f"xx Show {show_id} error (Status: {response.status_code})")
            return None

        soup = BeautifulSoup(response.content, 'html.parser')

        # --- AGGRESSIVE CLEANING ---
        remove_selectors = [
            {'id': ['comments', 'usercomments', 'shoutbox', 'sidebar', 'nav', 'foot']},
            {'class_': ['comments', 'comment-list', 'shoutbox', 'navigation', 'commentbody', 'user']}
        ]
        
        for selector in remove_selectors:
            for bad_section in soup.find_all(**selector):
                bad_section.decompose()

        # --- In Funk We Trust ---
        page_title = soup.title.string if soup.title else ""
        title_id_match = re.search(r'Show\s+(\d+)', page_title)
        
        if title_id_match:
            found_id = int(title_id_match.group(1))
            if found_id != show_id:
                print(f"xx Show {show_id} mismatch (Redirected to Show {found_id}) - Skipping.")
                return None
        else:
            print(f"xx Show {show_id} invalid (ID not found in page title) - Skipping.")
            return None
        # ----------------------------

        # 2. Extract Description
        desc_tag = soup.find('p', id='showdescription')
        show_description = clean_text(desc_tag.get_text()) if desc_tag else ""

        # 3. Extract Playlist
        playlist = []
        playlist_box = soup.find(id='playlistbox')
        if not playlist_box:
            playlist_box = soup.find('div', class_='playlist')

        if playlist_box:
            rows = playlist_box.find_all('div', recursive=False)
            if not rows:
                rows = playlist_box.find_all('li')

            for row in rows:
                entry = {}
                artist_tag = row.find(class_='artist')
                song_tag = row.find(class_='song')
                
                if artist_tag and song_tag:
                    entry['artist'] = clean_text(artist_tag.get_text())
                    entry['track'] = clean_text(song_tag.get_text())
                else:
                    text_content = clean_text(row.get_text())
                    if not text_content: continue
                    
                    if " - " in text_content:
                        parts = text_content.split(" - ", 1)
                        entry['artist'] = parts[0].strip()
                        entry['track'] = parts[1].strip()
                    else:
                        entry['artist'] = text_content
                        entry['track'] = ""

                note_tag = row.find(class_='note')
                if note_tag:
                    entry['note'] = clean_text(note_tag.get_text()).strip("()")
                
                if entry.get('artist') or entry.get('track'):
                    playlist.append(entry)

        if not playlist and not show_description:
            print(f"xx Show {show_id} appears empty - Skipping.")
            return None

        # 4. Extract Meta Info (DJs and Dates)
        recorded_date = "Unknown"
        djs = []
        
        # --- DJ Extraction ---
        credits_tag = soup.find('p', id='credits')
        if credits_tag:
            personnel_span = credits_tag.find('span', class_='personnel')
            if personnel_span:
                dj_string = clean_text(personnel_span.get_text())
                djs = [d.strip() for d in re.split(r',|&|/', dj_string) if d.strip()]

        # --- DATE EXTRACTION (Tri-Level Strategy) ---
        
        # Method A: Look for <b>RECORDED</b> tag (Older Shows)
        if recorded_date == "Unknown":
            rec_tag = soup.find('b', string=re.compile(r'RECORDED', re.IGNORECASE))
            if rec_tag:
                full_line = clean_text(rec_tag.parent.get_text())
                rec_match = re.search(r'RECORDED\s*[:\-]?\s*(.*?)(?:\s*[/|]|\s+HOSTING|\s*$)', full_line, re.IGNORECASE)
                if rec_match:
                    potential_date = clean_text(rec_match.group(1))
                    if re.search(r'(199|20[0-2])\d', potential_date):
                        recorded_date = potential_date

        # Method B: Search valid <a> links for MP3s (Recent Shows - Simple Link)
        if recorded_date == "Unknown":
            mp3_link = soup.find('a', href=re.compile(r'\.mp3$', re.IGNORECASE))
            if mp3_link:
                href_val = mp3_link['href']
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', href_val)
                if date_match:
                    recorded_date = date_match.group(1)
                    print(f"   (Date recovered from MP3 link: {recorded_date})")

        # Method C: GLOBAL REGEX SCAN (Recent Shows - Script/Hidden/Player)
        if recorded_date == "Unknown":
            full_html_text = str(soup)
            filename_match = re.search(r'WEFUNK_Show_\d+_(\d{4}-\d{2}-\d{2})', full_html_text)
            
            if filename_match:
                recorded_date = filename_match.group(1)
                print(f"   (Date recovered from Source Code Filename: {recorded_date})")

        # --- FORMATTING DATE ---
        # Convert YYYY-MM-DD to "Month DD, YYYY"
        recorded_date = format_date_string(recorded_date)

        # --- Extra Notes Extraction ---
        extra_notes_text = None
        extra_notes_links = []
        
        IGNORED_PHRASE = "Want to help out too? Please make a donation to support CKUT radio, WEFUNK's parent station."
        IGNORED_LINK_FRAGMENT = "ckut.ca/donate"

        notes_tag = soup.find(class_="extranotes smalltext")
        if notes_tag:
            temp_text = clean_text(notes_tag.get_text())
            if IGNORED_PHRASE in temp_text:
                temp_text = temp_text.replace(IGNORED_PHRASE, "").strip()
            
            if temp_text:
                extra_notes_text = temp_text

            links = notes_tag.find_all('a', href=True)
            for link in links:
                raw_href = link['href']
                clean_url = raw_href
                if "/clickout?" in raw_href:
                    parts = raw_href.split("?", 1)
                    if len(parts) > 1: clean_url = parts[1]
                
                if IGNORED_LINK_FRAGMENT in clean_url:
                    continue
                
                if clean_url.startswith("http"):
                    extra_notes_links.append(clean_url)

        meta_info = {
            "recorded": recorded_date,
            "djs": djs
        }
        
        if extra_notes_text:
            meta_info["extra_notes"] = extra_notes_text
            
        if extra_notes_links:
            meta_info["extra_notes_links"] = extra_notes_links

        show_data = {
            "meta_info": meta_info,
            "show_id": str(show_id),
            "url": url,
            "showdescription": show_description,
            "playlistbox": playlist
        }

        print(f"-> Processed Show {show_id}: Date='{recorded_date}', DJs={djs}, Links={len(extra_notes_links)}")
        return show_data

    except Exception as e:
        print(f"!! Error processing show {show_id}: {e}")
        return None

def get_valid_int(prompt):
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Invalid input. Please enter a number.")

def main():
    print("--- WEFUNK Radio Playlist Scraper/Archiver ---")
    start_show = get_valid_int("Enter START show number: ")
    end_show = get_valid_int("Enter END show number: ")

    if start_show > end_show:
        start_show, end_show = end_show, start_show

    output_file = f"wefunk_shows_{start_show}_{end_show}.json"
    
    print(f"\nStarting scrape from Show {start_show} to {end_show}...")
    print(f"Output will be saved to: {output_file}")
    
    all_shows = []
    
    try:
        for show_id in range(start_show, end_show + 1):
            data = parse_show(show_id)
            if data:
                all_shows.append(data)
            
            sleep_time = random.uniform(3, 5)
            if show_id % 50 == 0:
                print("   Taking a 10s break...")
                sleep_time = 10
            time.sleep(sleep_time)

            if show_id % 20 == 0:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(all_shows, f, indent=2, ensure_ascii=False)
                print(f"   [Saved progress]")

    except KeyboardInterrupt:
        print("\nStopping early...")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_shows, f, indent=2, ensure_ascii=False)
    
    print(f"\nDone. Scraped {len(all_shows)} shows. Saved to {output_file}")

if __name__ == "__main__":
    main()
