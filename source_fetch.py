"""Bounded public-source and image fetching. No private network destinations."""
import io, ipaddress, socket
from urllib.parse import urlsplit, urljoin
import requests
from bs4 import BeautifulSoup
from PIL import Image

def public_url(url):
    try:
        p=urlsplit(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):return False
        return all(ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(p.hostname,p.port or 443))
    except (ValueError,OSError):return False

def fetch_bytes(url,limit=6000000):
    for _ in range(5):
        if not public_url(url):raise ValueError('Only public article and image URLs are allowed.')
        with requests.get(url,headers={'User-Agent':'Mozilla/5.0 NewsletterResearch/1.0'},timeout=(8,20),allow_redirects=False,stream=True) as r:
            if r.is_redirect:url=urljoin(url,r.headers['Location']);continue
            r.raise_for_status();data=bytearray()
            for block in r.iter_content(65536):
                data.extend(block)
                if len(data)>limit:raise ValueError('Source exceeds the download limit.')
            return bytes(data),url
    raise ValueError('Too many source redirects.')

def fetch_article(url):
    data,resolved=fetch_bytes(url,3000000);soup=BeautifulSoup(data,'html.parser')
    title=soup.find('meta',property='og:title')
    title=title.get('content','') if title else (soup.title.get_text(' ',strip=True) if soup.title else '')
    image=soup.find('meta',property='og:image') or soup.find('meta',attrs={'name':'twitter:image'})
    image=urljoin(resolved,image.get('content','')) if image else ''
    for n in soup(['script','style','nav','footer','header','aside']):n.decompose()
    main=soup.find('article') or soup.find('main') or soup.body or soup
    text='\n'.join(p.get_text(' ',strip=True) for p in main.find_all('p'))
    if len(text)<200:raise ValueError('The source could not be extracted. Supply the original article text and retry.')
    return {'title':title,'text':text[:50000],'image_url':image}

def fetch_image(url):
    data,_=fetch_bytes(url)
    with Image.open(io.BytesIO(data)) as im:
        if im.width*im.height>25000000:raise ValueError('Image is too large.')
        if im.width<200 or im.height<100:raise ValueError('Image resolution is too low for the newsletter.')
        out=io.BytesIO();im.convert('RGB').save(out,'JPEG',quality=94)
        return out.getvalue()
