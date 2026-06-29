import io, gc, time, html, re
import asyncio
import aiohttp
import orjson
from aiohttp import web
from bson.objectid import ObjectId
from utils import temp
from info import THUMBNAIL_STORAGE_CHANNEL
from database.users_chats_db import db as motor_db
from web.web_assets import build_page, get_auth, form_wrapper

post_routes = web.RouteTableDef()
posts_col = motor_db.db["Posts"]

# ─────────────────────────────────────────────────────────
# ⚡ ULTRA-FAST ORJSON DUMP FUNCTION
# ─────────────────────────────────────────────────────────
def fast_json(data):
    return orjson.dumps(data).decode('utf-8')

# ─────────────────────────────────────────────────────────
# 🛠️ ImgBB Auto-Converter Helper Functions
# ─────────────────────────────────────────────────────────
async def fetch_direct_ibb_url(session, url):
    url = url.strip()
    if not url: return None
    # अगर यह ImgBB का Viewer लिंक है (जिसमें i.ibb.co नहीं है)
    if "ibb.co" in url and "i.ibb.co" not in url:
        try:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    html_content = await resp.text()
                    # HTML सोर्स से डायरेक्ट इमेज लिंक (og:image) निकालना
                    match = re.search(r'<meta property="og:image" content="([^"]+)"', html_content)
                    if match:
                        return match.group(1)
        except Exception:
            pass
    return url

async def convert_all_ibb_links(urls):
    """सारे लिंक्स को एक साथ (Concurrently) कन्वर्ट करता है ताकि सर्वर स्लो न हो"""
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_direct_ibb_url(session, u) for u in urls if u.strip()]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r]

# ─────────────────────────────────────────────────────────
# 📝 1. ADMIN ROUTE: CREATE POST WIZARD (UI)
# ─────────────────────────────────────────────────────────
@post_routes.get('/admin/create_post')
async def create_post_page(req):
    role, _ = await get_auth(req)
    if role != 'admin': 
        return web.HTTPFound('/dashboard')
    
    html_content = '''
    <style>
        .em-input { width:100%; background:var(--bg); border:1px solid var(--border); padding:12px; color:var(--text); margin-bottom:15px; border-radius:6px; outline:none; font-family:inherit; }
        .em-input:focus { border-color:var(--accent); }
        .scard-label { font-size:13px; font-weight:700; color:var(--muted); margin-bottom:8px; text-transform:uppercase; letter-spacing:1px; }
        .step-box { background:var(--card); border:1px solid var(--border); padding:25px; border-radius:12px; margin-bottom:20px; box-shadow:0 8px 25px rgba(0,0,0,0.2); }
    </style>

    <div class="main" style="max-width:850px; margin:30px auto; padding:0 20px;">
        <h2 style="font-size:28px; font-weight:900; margin-bottom:25px; color:var(--text); display:flex; justify-content:space-between; align-items:center;">
            <span>📝 Create New Post</span>
            <a href="/posts" style="font-size:14px; font-weight:700; color:var(--muted); text-decoration:none;">← Back to Posts</a>
        </h2>
        
        <form action="/api/post/publish" method="post" enctype="multipart/form-data">
            
            <div class="step-box">
                <div class="scard-label">1. Post Title</div>
                <input type="text" name="title" placeholder="e.g. Pushpa 2: The Rule (2024)" class="em-input" required>
                
                <div class="scard-label" style="margin-top:10px;">2. Short Description</div>
                <textarea name="description" placeholder="Write a short description or synopsis..." class="em-input" style="min-height:120px;" required></textarea>
                
                <div class="scard-label" style="margin-top:10px;">3. Search Tags (Comma Separated)</div>
                <input type="text" name="tags" placeholder="e.g. Allu Arjun, Action, 2024, Hindi Dubbed" class="em-input">
            </div>

            <div class="step-box">
                <div class="scard-label">4. Cover Image</div>
                <input type="url" name="cover_url" placeholder="Paste ibb.co Link (Viewer or Direct)" class="em-input" style="margin-bottom:10px;">
                <div style="text-align:center; color:var(--muted); margin-bottom:10px; font-weight:800; font-size:12px;">OR UPLOAD FILE</div>
                <input type="file" name="cover_file" accept="image/*" class="em-input" style="padding:8px;">
            </div>

            <div class="step-box">
                <div class="scard-label">5. Screenshots (Multiple)</div>
                <textarea name="screenshot_urls" placeholder="Paste ibb.co links line by line...&#10;https://ibb.co/gcBG365&#10;https://ibb.co/Mx01rc6L" class="em-input" style="min-height:100px; white-space:pre-wrap; margin-bottom:10px;"></textarea>
                <div style="text-align:center; color:var(--muted); margin-bottom:10px; font-weight:800; font-size:12px;">AND / OR UPLOAD FILES</div>
                <input type="file" name="screenshot_files" accept="image/*" multiple class="em-input" style="padding:8px;">
            </div>

            <div class="step-box" style="border-color:var(--accent);">
                <div class="scard-label" style="color:var(--accent);">6. Add Videos (Search Indexed Files)</div>
                <div style="display:flex; gap:10px; margin-bottom:10px;">
                    <input type="text" id="videoSearchInput" placeholder="Search movie/series in database..." class="em-input" style="margin-bottom:0;" onkeydown="if(event.key==='Enter'){ event.preventDefault(); searchVideosForPost(); }">
                    <button type="button" onclick="searchVideosForPost()" style="background:var(--accent); color:#fff; border:none; padding:0 24px; border-radius:6px; font-weight:800; cursor:pointer;">Search</button>
                </div>
                
                <div id="videoSearchResults" style="background:var(--bg2); border:1px solid var(--border); border-radius:6px; max-height:250px; overflow-y:auto; display:none; margin-bottom:20px; box-shadow:0 4px 15px rgba(0,0,0,0.5);"></div>
                
                <div class="scard-label">Selected Qualities:</div>
                <div id="selectedVideosContainer" style="display:flex; flex-direction:column; gap:10px; min-height:50px; padding:10px; background:var(--bg); border-radius:8px; border:1px dashed var(--border);"></div>
            </div>

            <button type="submit" style="width:100%; background:var(--accent); color:#fff; border:none; padding:16px; border-radius:8px; font-weight:800; font-size:16px; cursor:pointer; box-shadow:0 8px 25px rgba(229,9,20,0.4); transition:0.2s;" onmouseover="this.style.transform='scale(1.02)'" onmouseout="this.style.transform='scale(1)'">🚀 Publish Post</button>
        </form>
    </div>

    <script>
    async function searchVideosForPost() {
        const q = document.getElementById('videoSearchInput').value.trim();
        if(!q) return;
        
        const resDiv = document.getElementById('videoSearchResults');
        resDiv.style.display = 'block';
        resDiv.innerHTML = '<div style="padding:15px; color:var(--muted); text-align:center; font-weight:bold;">🔍 Searching database...</div>';
        
        try {
            const response = await fetch('/api/search?q=' + encodeURIComponent(q) + '&mode=none');
            const data = await response.json();
            
            if(!data.results || data.results.length === 0) {
                resDiv.innerHTML = '<div style="padding:15px; color:var(--muted); text-align:center;">❌ No indexed files found.</div>';
                return;
            }
            
            let html = '';
            data.results.forEach(f => {
                const safeName = f.name.replace(/'/g, "\\'").replace(/"/g, "&quot;");
                html += `
                <div style="padding:12px 15px; border-bottom:1px solid var(--border); cursor:pointer; transition:0.2s;" onmouseover="this.style.background='var(--bg3)'" onmouseout="this.style.background='transparent'" onclick="addVideoToPost('${f.file_id}', '${safeName}')">
                    <div style="font-weight:700; font-size:13px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${f.name}</div>
                    <div style="font-size:11px; color:var(--muted); margin-top:4px;">
                        <span style="background:var(--bg4); padding:2px 6px; border-radius:4px;">${f.size}</span>
                        <span style="background:var(--bg4); padding:2px 6px; border-radius:4px; margin-left:5px;">${f.source}</span>
                    </div>
                </div>`;
            });
            resDiv.innerHTML = html;
        } catch(e) {
            resDiv.innerHTML = '<div style="padding:15px; color:var(--accent); text-align:center;">⚠️ API Error!</div>';
        }
    }

    function addVideoToPost(fileId, fileName) {
        document.getElementById('videoSearchResults').style.display = 'none';
        const container = document.getElementById('selectedVideosContainer');
        
        const div = document.createElement('div');
        div.style.cssText = "background:var(--card); border:1px solid var(--accent); padding:15px; border-radius:8px; display:flex; gap:15px; align-items:center;";
        
        div.innerHTML = `
            <div style="flex:1; min-width:0;">
                <div style="font-size:11px; color:var(--muted); margin-bottom:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${fileName}">📁 ${fileName}</div>
                <input type="hidden" name="video_id" value="${fileId}">
                <input type="text" name="video_name" placeholder="Custom Name (e.g. 1080p WEB-DL)" class="em-input" style="margin-bottom:0; font-weight:800; color:var(--accent);" required>
            </div>
            <button type="button" onclick="this.parentElement.remove()" style="background:rgba(160,8,8,0.8); color:#fff; border:none; padding:10px 15px; border-radius:6px; cursor:pointer; font-weight:bold; height:fit-content;">✖</button>
        `;
        container.appendChild(div);
    }
    </script>
    '''
    return build_page("Create Post", form_wrapper("New Post", html_content, req.query.get('err',''), req.query.get('msg','')), "login-bg", "posts", role)

# ─────────────────────────────────────────────────────────
# ⚙️ 2. API: PUBLISH POST (With ImgBB Auto-Converter)
# ─────────────────────────────────────────────────────────
@post_routes.post('/api/post/publish')
async def api_publish_post(req):
    role, _ = await get_auth(req)
    if role != 'admin': 
        return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    
    try:
        reader = await req.multipart()
        
        post_data = {
            "title": "", "description": "", "cover_image": "", 
            "screenshots": [], "videos": [], "tags": [], "created_at": int(time.time())
        }
        screenshot_urls_raw = ""
        temp_v_ids, temp_v_names = [], []
        
        while True:
            part = await reader.next()
            if part is None: break
                
            p_name = part.name
            if p_name == 'title': post_data["title"] = (await part.read()).decode().strip()
            elif p_name == 'description': post_data["description"] = (await part.read()).decode().strip()
            elif p_name == 'tags': 
                post_data["tags"] = [t.strip() for t in (await part.read()).decode().strip().split(",") if t.strip()]
            
            # --- VIDEO DATA ARRAYS ---
            elif p_name == 'video_id': temp_v_ids.append((await part.read()).decode().strip())
            elif p_name == 'video_name': temp_v_names.append((await part.read()).decode().strip())
            
            # --- COVER IMAGE ---
            elif p_name == 'cover_url':
                url = (await part.read()).decode().strip()
                if url: post_data["cover_image"] = url
            elif p_name == 'cover_file' and part.filename and not post_data["cover_image"]:
                img_bytes = await part.read()
                with io.BytesIO(img_bytes) as img_buf:
                    img_buf.name = "cover.jpg"
                    msg = await temp.BOT.send_photo(chat_id=THUMBNAIL_STORAGE_CHANNEL, photo=img_buf)
                    if msg and msg.photo:
                        tg_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
                        post_data["cover_image"] = f"TG_ID:{tg_id}"
                        
            # --- SCREENSHOTS ---
            elif p_name == 'screenshot_urls':
                screenshot_urls_raw = (await part.read()).decode().strip()
            elif p_name == 'screenshot_files' and part.filename:
                img_bytes = await part.read()
                with io.BytesIO(img_bytes) as img_buf:
                    img_buf.name = f"ss_{int(time.time())}.jpg"
                    msg = await temp.BOT.send_photo(chat_id=THUMBNAIL_STORAGE_CHANNEL, photo=img_buf)
                    if msg and msg.photo:
                        tg_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
                        post_data["screenshots"].append(f"TG_ID:{tg_id}")

        # 🚀 1. Cover Image Auto-Convert Logic
        if post_data["cover_image"] and "ibb.co" in post_data["cover_image"]:
            converted_cover = await convert_all_ibb_links([post_data["cover_image"]])
            if converted_cover:
                post_data["cover_image"] = converted_cover[0]

        # 🚀 2. Screenshots Auto-Convert Logic
        if screenshot_urls_raw:
            raw_urls = [u.strip() for u in screenshot_urls_raw.split('\n') if u.strip()]
            direct_urls = await convert_all_ibb_links(raw_urls)
            post_data["screenshots"].extend(direct_urls)
            
        for vid, vname in zip(temp_v_ids, temp_v_names):
            if vid and vname:
                post_data["videos"].append({"file_id": vid, "custom_name": vname})

        await posts_col.insert_one(post_data)
        return web.HTTPFound('/posts?msg=Post published successfully!')
        
    except Exception as e:
        return web.HTTPFound(f'/admin/create_post?err=Server Error: {str(e)}')


# ─────────────────────────────────────────────────────────
# 🖼️ 3. API: SERVE TELEGRAM IMAGES FOR POSTS
# ─────────────────────────────────────────────────────────
@post_routes.get('/api/post/photo')
async def get_post_photo(req):
    tg_id = req.query.get("id")
    if not tg_id: return web.Response(status=400)
    try:
        file_data = await temp.BOT.download_media(tg_id, in_memory=True)
        if not file_data: return web.Response(status=404)
        body_bytes = file_data.getvalue()
        file_data.close()
        return web.Response(body=body_bytes, content_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000"})
    except: return web.Response(status=500)
    finally: gc.collect()


# ─────────────────────────────────────────────────────────
# 🌐 4. PUBLIC ROUTE: POSTS DIRECTORY GRID (Mobile:2, Desk:5)
# ─────────────────────────────────────────────────────────
@post_routes.get('/posts')
async def posts_directory_page(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    
    all_posts = await posts_col.find({}).sort("created_at", -1).limit(21).to_list(length=21)
    has_next_init = len(all_posts) > 20
    all_posts = all_posts[:20]
    
    admin_btn = '''<button onclick="window.location.href='/admin/create_post'" style="background:var(--accent); color:#fff; border:none; padding:0 24px; border-radius:8px; font-weight:800; cursor:pointer; white-space:nowrap;">➕ Create</button>''' if role == 'admin' else ""
    
    search_ui = f'''
    <style>
        .dir-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
        @media(min-width: 768px) {{ .dir-grid {{ grid-template-columns: repeat(5, 1fr); gap: 20px; }} }}
        .search-box {{ background:var(--card); border:1px solid var(--border); padding:16px; border-radius:12px; margin-bottom:25px; box-shadow:0 4px 15px rgba(0,0,0,0.1); display:flex; gap:10px; }}
        .s-input {{ flex:1; background:var(--bg3); border:1px solid var(--border); padding:12px 16px; color:var(--text); border-radius:8px; outline:none; font-weight:600; font-size:14px; font-family:inherit; }}
        .pg-bar {{ display:flex; justify-content:center; align-items:center; gap:15px; margin-top:30px; }}
    </style>

    <div class="search-box">
        <input type="text" id="post_q" class="s-input" placeholder="Search movies, series, posts...">
        <button onclick="resetPost(); searchPosts()" style="background:var(--bg4); color:var(--text); border:1px solid var(--border); padding:0 24px; border-radius:8px; font-weight:800; cursor:pointer;">Search</button>
        {admin_btn}
    </div>
    '''

    post_items = ""
    for p in all_posts:
        cover = p.get("cover_image", "")
        img_src = f"/api/post/photo?id={cover.replace('TG_ID:', '')}" if cover.startswith("TG_ID:") else cover
        post_items += f'''
        <div class="act-card card-enter" onclick="window.location.href='/post/{str(p["_id"])}'">
            <div style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">
                <img src="{img_src}" class="act-poster" loading="lazy">
                <div style="position:absolute; top:8px; left:8px; background:rgba(229,9,20,0.9); color:#fff; font-size:9px; padding:4px 8px; border-radius:4px; font-weight:800; backdrop-filter:blur(4px); z-index:2;">🎬 POST</div>
            </div>
            <div style="padding:12px; text-align:center;">
                <div style="font-size:13.5px; font-weight:800; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{html.escape(p.get("title", "Untitled"))}</div>
            </div>
        </div>'''
    
    initial_grid = f'<div id="post_grid_container" class="dir-grid">{post_items}</div>' if all_posts else '<div style="text-align:center; padding:60px 20px; color:var(--muted);">No posts found.</div>'

    js_logic = f'''
    <div class="pg-bar" id="post_pg_box" style="display:{'flex' if has_next_init else 'none'};">
        <button class="pg-btn" id="post_pBtn" onclick="prevPost()" disabled>Previous</button>
        <span class="pg-info" id="post_pgInfo" style="font-weight:800;">Page 1</span>
        <button class="pg-btn" id="post_nBtn" onclick="nextPost()">Next</button>
    </div>

    <script>
    var pOff = 0, pLim = 20, pPage = 1, pNext = {str(has_next_init).lower()};
    
    async function searchPosts() {{
        var q = document.getElementById('post_q').value.trim();
        var grid = document.getElementById('post_grid_container');
        grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:40px; color:var(--muted); font-weight:bold;">🔄 Searching Catalog...</div>';
        try {{
            var res = await fetch(`/api/posts/search?q=${{encodeURIComponent(q)}}&offset=${{pOff}}`);
            var data = await res.json();
            grid.innerHTML = data.html;
            staggerCards(grid);
            pNext = data.has_next;
            updatePgUI();
        }} catch(e) {{ grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--accent);">Error loading posts!</div>'; }}
    }}
    
    function updatePgUI() {{
        var box = document.getElementById('post_pg_box');
        box.style.display = (pOff === 0 && !pNext) ? 'none' : 'flex';
        document.getElementById('post_pBtn').disabled = (pOff === 0);
        document.getElementById('post_nBtn').disabled = !pNext;
        document.getElementById('post_pgInfo').innerText = 'Page ' + pPage;
    }}
    
    function resetPost() {{ pOff = 0; pPage = 1; }}
    function nextPost() {{ if(pNext) {{ pOff += pLim; pPage++; searchPosts(); window.scrollTo(0, 50); }} }}
    function prevPost() {{ if(pOff > 0) {{ pOff = Math.max(0, pOff - pLim); pPage--; searchPosts(); window.scrollTo(0, 50); }} }}
    
    document.getElementById('post_q').addEventListener('keydown', e => {{ if(e.key === 'Enter') {{ resetPost(); searchPosts(); }} }});

    // पेज लोड होते ही ग्रिड एनिमेशन चालू करने के लिए 🚀
    document.addEventListener("DOMContentLoaded", () => {{
        var grid = document.getElementById('post_grid_container');
        if(grid && typeof staggerCards === 'function') staggerCards(grid);
    }});
    </script>
    '''

    page_body = f'<div class="main" style="padding-top:20px; max-width:1100px; margin:0 auto; padding-left:20px; padding-right:20px;">{search_ui}{initial_grid}{js_logic}</div>'
    return build_page("Posts Catalog", page_body, "", "posts", role)

# ─────────────────────────────────────────────────────────
# 🔍 5. API: SEARCH POSTS (With Pagination)
# ─────────────────────────────────────────────────────────
@post_routes.get('/api/posts/search')
async def api_posts_search(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"html": ""}, dumps=fast_json)
    
    q = req.query.get("q", "").strip()
    try: offset = int(req.query.get("offset", 0))
    except: offset = 0
    lim = 20
    
    query = {}
    if q: 
        safe_q = re.escape(q)
        query["$or"] = [{"title": {"$regex": safe_q, "$options": "i"}}, {"tags": {"$regex": safe_q, "$options": "i"}}]
        
    docs = await posts_col.find(query).sort("created_at", -1).skip(offset).limit(lim + 1).to_list(length=lim + 1)
    has_next = len(docs) > lim
    docs = docs[:lim]
    
    if not docs:
        return web.json_response({"html": '<div style="grid-column:1/-1; text-align:center; color:var(--muted); padding:40px;">No posts matching your search.</div>', "has_next": False}, dumps=fast_json)
        
    html_out = ""
    for p in docs:
        cover = p.get("cover_image", "")
        img_src = f"/api/post/photo?id={cover.replace('TG_ID:', '')}" if cover.startswith("TG_ID:") else cover
        html_out += f'''
        <div class="act-card card-enter" onclick="window.location.href='/post/{str(p["_id"])}'">
            <div style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">
                <img src="{img_src}" class="act-poster" loading="lazy">
                <div style="position:absolute; top:8px; left:8px; background:rgba(229,9,20,0.9); color:#fff; font-size:9px; padding:4px 8px; border-radius:4px; font-weight:800; backdrop-filter:blur(4px); z-index:2;">🎬 POST</div>
            </div>
            <div style="padding:12px; text-align:center;">
                <div style="font-size:13.5px; font-weight:800; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{html.escape(p.get("title", "Untitled"))}</div>
            </div>
        </div>'''
            
    return web.json_response({"html": html_out, "has_next": has_next}, dumps=fast_json)

# ─────────────────────────────────────────────────────────
# 🍿 6. PUBLIC ROUTE: SINGLE POST VIEW
# ─────────────────────────────────────────────────────────
@post_routes.get('/post/{id}')
async def single_post_display(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    
    try:
        post = await posts_col.find_one({"_id": ObjectId(req.match_info['id'])})
        if not post: return web.Response(text="Post Not Found", status=404)
    except: return web.Response(text="Invalid ID", status=400)
    
    cover = post.get("cover_image", "")
    img_src = f"/api/post/photo?id={cover.replace('TG_ID:', '')}" if cover.startswith("TG_ID:") else cover
    
    tags_html = "".join([f'<span style="background:var(--bg3); border:1px solid var(--border); color:var(--muted); font-size:11px; padding:4px 10px; border-radius:4px; font-weight:700;">#{html.escape(t)}</span>' for t in post.get("tags", [])])
    tags_div = f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin-top:12px;">{tags_html}</div>' if tags_html else ""
    
    video_buttons = ""
    for v in post.get("videos", []):
        video_buttons += f'''<a href="/setup_stream?file_id={v.get('file_id')}&mode=watch" target="_blank" style="display:inline-block; background:var(--accent); color:#fff; font-weight:800; font-size:14px; text-decoration:none; padding:14px 28px; border-radius:8px; box-shadow:0 4px 15px rgba(229,9,20,0.3); transition:transform 0.2s;" onmouseover="this.style.transform='scale(1.04)'" onmouseout="this.style.transform='scale(1)'">▶ {html.escape(v.get("custom_name", "Play / Download"))}</a>'''
    
    ss_html = ""
    for ss in post.get("screenshots", []):
        s_src = f"/api/post/photo?id={ss.replace('TG_ID:', '')}" if ss.startswith("TG_ID:") else ss
        ss_html += f'<div style="border:1px solid var(--border); border-radius:8px; overflow:hidden; aspect-ratio:16/9; background:var(--bg3); box-shadow:0 4px 15px rgba(0,0,0,0.2);"><img src="{s_src}" style="width:100%; height:100%; object-fit:cover; cursor:pointer; transition:0.3s;" onmouseover="this.style.transform=\'scale(1.03)\'" onmouseout="this.style.transform=\'scale(1)\'" onclick="window.open(this.src, \'_blank\')"></div>'
    
    gallery_grid = f'<h3 style="font-size:20px; font-weight:800; color:var(--text); border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:20px; margin-top:40px;">📸 Screenshots</h3><div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(250px, 1fr)); gap:20px;">{ss_html}</div>' if ss_html else ""

    page_body = f'''
    <div class="main" style="max-width:950px; margin:30px auto; padding:0 20px;">
        <div style="margin-bottom:20px;">
            <a href="/posts" style="color:var(--muted); text-decoration:none; font-size:14px; font-weight:800;">← Back to Catalog</a>
        </div>
        
        <div style="background:var(--card); border:1px solid var(--border); border-radius:16px; overflow:hidden; box-shadow:0 12px 40px rgba(0,0,0,0.3);">
            <div style="width:100%; aspect-ratio:21/9; background:url('{img_src}') center/cover; position:relative;">
                <div style="position:absolute; inset:0; background:linear-gradient(to top, var(--card) 0%, transparent 100%);"></div>
                <div style="position:absolute; bottom:25px; left:30px; right:30px;">
                    <h1 style="font-size:36px; font-weight:900; color:var(--text); margin-bottom:5px; text-shadow:0 2px 10px rgba(0,0,0,0.8);">{html.escape(post.get("title", ""))}</h1>
                    {tags_div}
                </div>
            </div>
            
            <div style="padding:35px 30px;">
                <div style="font-size:16px; color:var(--text); line-height:1.7; margin-bottom:40px; white-space:pre-line; font-weight:500;">
                    {html.escape(post.get("description", ""))}
                </div>
                
                <h3 style="font-size:20px; font-weight:800; color:var(--text); border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:25px;">🍿 Download / Watch Links</h3>
                <div style="display:flex; flex-wrap:wrap; gap:15px;">
                    {video_buttons if video_buttons else '<div style="color:var(--muted); font-size:14px; font-weight:bold;">No media attached.</div>'}
                </div>
                
                {gallery_grid}
            </div>
        </div>
    </div>
    '''
    return build_page(f"{post.get('title', 'Post')} - Catalog", page_body, "", "posts", role)
