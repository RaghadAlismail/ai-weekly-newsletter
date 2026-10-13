"""Fill the supplied Arabic PowerPoint template without changing its layout."""
import io, os, zipfile
from pathlib import Path
from lxml import etree as E
from cryptography.fernet import Fernet
from PIL import Image, ImageOps
import qrcode

NS={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL='http://schemas.openxmlformats.org/package/2006/relationships'

def template_bytes():
    key=os.getenv('NEWSLETTER_TEMPLATE_KEY','')
    if not key:raise RuntimeError('The Arabic slide template is not configured.')
    return Fernet(key.encode()).decrypt((Path(__file__).parent/'newsletter-template.enc').read_bytes())

def replace_text(shape,text):
    nodes=shape.findall('.//a:t',NS)
    if not nodes:return
    nodes[0].text=str(text)
    for n in nodes[1:]:n.text=''

def build_deck(snapshot,images):
    if len(snapshot['articles'])!=10:raise ValueError('Exactly ten articles are required.')
    with zipfile.ZipFile(io.BytesIO(template_bytes())) as source:
        files={n:source.read(n) for n in source.namelist()}
    for index,article in enumerate(snapshot['articles'],2):
        name=f'ppt/slides/slide{index}.xml';root=E.fromstring(files[name])
        relname=f'ppt/slides/_rels/slide{index}.xml.rels';rels=E.fromstring(files[relname])
        def newrel(kind,target,external=False):
            rid='rIdNewsletter'+str(len(rels)+1)
            attrs={'Id':rid,'Type':f'http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}','Target':target}
            if external:attrs['TargetMode']='External'
            E.SubElement(rels,'{'+REL+'}Relationship',**attrs)
            return rid
        for shape in root.findall('.//p:spTree/*',NS):
            off=shape.find('.//a:xfrm/a:off',NS);ext=shape.find('.//a:xfrm/a:ext',NS)
            if off is None or ext is None:continue
            y=int(off.get('y'));w=int(ext.get('cx'));h=int(ext.get('cy'))
            tag=E.QName(shape).localname
            if tag=='sp':
                if w>1500000 and 1100000<y<1450000:replace_text(shape,article['headline'])
                elif w<500000 and 1100000<y<1250000:replace_text(shape,article['category'])
                elif w>1500000 and y>1400000 and h>500000:replace_text(shape,article['body'])
                text=''.join(shape.xpath('.//a:t/text()',namespaces=NS)).strip()
                if text=='اضغط هنا':
                    for run in shape.findall('.//a:r',NS):
                        props=run.find('a:rPr',NS)
                        if props is None:props=E.SubElement(run,'{'+NS['a']+'}rPr')
                        for old in props.findall('a:hlinkClick',NS):props.remove(old)
                        E.SubElement(props,'{'+NS['a']+'}hlinkClick',**{'{'+NS['r']+'}id':newrel('hyperlink',article['url'],True)})
            elif tag=='pic':
                if w>2000000 and h>700000:
                    image=images.get(article['id'])
                    if not image:raise ValueError(f'Article {index-1} needs an image before the deck can be built.')
                    im=Image.open(io.BytesIO(image)).convert('RGB')
                    im=ImageOps.fit(im,(1600,round(1600*h/w)),method=Image.Resampling.LANCZOS)
                    output=io.BytesIO();im.save(output,'JPEG',quality=94)
                    media=f'newsletter-{index}-image.jpg';files['ppt/media/'+media]=output.getvalue()
                elif 100000<w<300000 and h<300000:
                    output=io.BytesIO();qrcode.make(article['url']).save(output,format='PNG')
                    media=f'newsletter-{index}-qr.png';files['ppt/media/'+media]=output.getvalue()
                else:continue
                blip=shape.find('.//a:blip',NS)
                if blip is not None:blip.set('{'+NS['r']+'}embed',newrel('image','../media/'+media))
                for crop in shape.findall('.//a:srcRect',NS):crop.getparent().remove(crop)
        for rel in rels:
            if rel.get('Type','').endswith('/hyperlink') and rel.get('TargetMode')=='External':rel.set('Target',article['url'])
        files[name]=E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
        files[relname]=E.tostring(rels,xml_declaration=True,encoding='UTF-8',standalone=True)
    cover=E.fromstring(files['ppt/slides/slide1.xml'])
    for shape in cover.findall('.//p:sp',NS):
        text=''.join(shape.xpath('.//a:t/text()',namespaces=NS))
        if 'العدد' in text:replace_text(shape,'العدد '+str(snapshot['issue']))
        elif any(m in text for m in ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']):replace_text(shape,snapshot['date'])
    files['ppt/slides/slide1.xml']=E.tostring(cover,xml_declaration=True,encoding='UTF-8',standalone=True)
    types=E.fromstring(files['[Content_Types].xml']);ct='{http://schemas.openxmlformats.org/package/2006/content-types}'
    for ext,mime in [('jpg','image/jpeg'),('png','image/png')]:
        if not any(n.get('Extension')==ext for n in types):E.SubElement(types,ct+'Default',Extension=ext,ContentType=mime)
    files['[Content_Types].xml']=E.tostring(types,xml_declaration=True,encoding='UTF-8',standalone=True)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
    return out.getvalue()
