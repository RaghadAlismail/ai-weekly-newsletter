"""Whole-newsletter generation and ordered reviewer handoffs."""
import base64, io, json, os, threading, time
from concurrent.futures import ThreadPoolExecutor
from flask import request, session, abort, flash, redirect, url_for, render_template, send_file, jsonify
from storage import migrate_workflow
from deck_builder import build_deck

STEPS=['owner_review','content_review','design_review','final_review']
LABELS={'draft':'Ready to generate','generating':'Generating Arabic slides','generation_failed':'Generation needs attention','owner_review':'Your review','content_review':'Second reviewer','design_review':'Designer','final_review':'Final reviewer','approved':'Final approved'}
ASSIGNEE={'owner_review':'owner_email','content_review':'reviewer_email','design_review':'designer_email','final_review':'final_email'}

def check_edit(issue,email,role):
    stage=issue['workflow_stage']
    if stage in ('draft','generation_failed'):
        if email!=issue['owner_email'] and role not in ('admin','coordinator'):abort(403)
    elif stage not in ASSIGNEE or email.casefold()!=issue[ASSIGNEE[stage]].casefold():
        abort(403,'Only the currently assigned reviewer can edit this newsletter.')

def register_workflow(app,h):
    db=h['db'];issue=h['issue'];actor=h['actor'];role=h['role'];require=h['require_login'];people=h['authorized_people'];audit=h['audit']
    migrate_workflow(h['DATA'])
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS validated_article_generations (article_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL)')
    # In-process jobs remain resumable: an interrupted job exposes a retry action.
    active=set();lock=threading.Lock()
    def rows(iid):
        with db() as c:return [dict(x) for x in c.execute('SELECT * FROM articles WHERE issue_id=? ORDER BY position',(iid,)).fetchall()]
    def snapshot(iid):
        i=issue(iid);return {'issue':i['number'],'date':i['pub_date'],'articles':rows(iid)}
    def media(iid):
        with db() as c:return {r['article_id']:base64.b64decode(r['payload']) for r in c.execute('SELECT m.* FROM article_media m JOIN articles a ON a.id=m.article_id WHERE a.issue_id=?',(iid,)).fetchall()}
    def save_version(c,iid,who,reason):
        i=c.execute('SELECT * FROM issues WHERE id=?',(iid,)).fetchone()
        aa=[dict(a) for a in c.execute('SELECT * FROM articles WHERE issue_id=? ORDER BY position',(iid,)).fetchall()]
        c.execute('INSERT INTO issue_versions(issue_id,revision,snapshot,actor,reason) VALUES(?,?,?,?,?)',(iid,i['content_revision'],json.dumps(aa,ensure_ascii=False),who,reason))
    def touch(iid,reason,text_changed=True,connection=None):
        def update(c):
            i=c.execute('SELECT * FROM issues WHERE id=?',(iid,)).fetchone()
            stage=i['workflow_stage']
            if text_changed and stage in ('content_review','design_review','final_review'):stage='owner_review'
            elif not text_changed and stage=='final_review':stage='design_review'
            c.execute('UPDATE issues SET content_revision=content_revision+1,workflow_stage=? WHERE id=?',(stage,iid))
            save_version(c,iid,actor(),reason)
            c.execute('DELETE FROM generated_decks WHERE issue_id=?',(iid,))
            audit(c,iid,None,'revision_saved',{'stage':stage,'reason':reason})
        if connection is not None:update(connection)
        else:
            with db() as c:update(c)
    h['touch']=touch;h['snapshot']=snapshot;h['media']=media

    def process(a):
        from source_fetch import fetch_article,fetch_image
        from write_summary import write_summary,detect_category
        from review_summary import review_summary
        from fact_checker import fact_check
        source={'title':a['source_title'],'text':a['supplied_content'] or a['source_text'],'image_url':a['image_url']}
        if len(source['text'].strip())<200:
            extracted=fetch_article(a['url'])
            source['title']=source['title'] or extracted['title'];source['text']=extracted['text'];source['image_url']=source['image_url'] or extracted['image_url']
        if len(source['text'].strip())<200:raise ValueError('Provide sufficient original source text.')
        with db() as c:
            c.execute('UPDATE articles SET source_title=?,source_text=?,image_url=? WHERE id=?',(source['title'],source['text'],source['image_url'],a['id']))
        en,ar=detect_category(source['title'],source['text'])
        category=a['category'] or ar
        if category not in h['CATEGORIES']:category='دراسات' if en in ('Studies','Universities') else 'شركات'
        from generation_quality import validate_copy
        result=write_summary(source['title'],source['text'],en)
        result=validate_copy(result, en, source['title'], source['text'], review_summary, fact_check)
        title=str(result.get('title_ar','')).strip();body=str(result.get('body_ar','')).strip()
        with db() as c:stored=c.execute('SELECT payload FROM article_media WHERE article_id=?',(a['id'],)).fetchone()
        image=base64.b64decode(stored['payload']) if stored else (fetch_image(source['image_url']) if source['image_url'] else None)
        if not image:raise ValueError('No usable source image was found. Add an image URL or upload an image, then retry.')
        with db() as c:
            c.execute('UPDATE articles SET source_title=?,source_text=?,extract_status=?,headline=?,body=?,category=?,image_url=?,extract_notes=?,revision=revision+1 WHERE id=?',(source['title'],source['text'],'supplied' if a['supplied_content'] else 'ready',title,body,category,source['image_url'],'',a['id']))
            c.execute('INSERT INTO article_media(article_id,payload) VALUES(?,?) ON CONFLICT(article_id) DO UPDATE SET payload=excluded.payload',(a['id'],base64.b64encode(image).decode()))
            revision=c.execute('SELECT revision FROM articles WHERE id=?',(a['id'],)).fetchone()['revision']
            c.execute('INSERT INTO validated_article_generations(article_id,revision) VALUES(?,?) ON CONFLICT(article_id) DO UPDATE SET revision=excluded.revision',(a['id'],revision))

    def run(iid,who,article_ids=None):
        with app.app_context():
            try:
                failures=[]
                def guarded(a):
                    try:
                        process(a)
                    except Exception as ex:
                        message=f"Article {a['position']}: {str(ex)[:180]}"
                        # API exception text can include URLs, so hide external error details.
                        if 'api.openai.com' in message:message=f"Article {a['position']}: AI service rejected the request. Check the configured model and API account."
                        with db() as c:c.execute('UPDATE articles SET extract_notes=? WHERE id=?',(message,a['id']))
                        return message
                with ThreadPoolExecutor(max_workers=1) as pool:
                    targets=[a for a in rows(iid) if article_ids is None or a['id'] in article_ids]
                    failures=[x for x in pool.map(guarded,targets) if x]
                all_rows=rows(iid);all_media=media(iid)
                failures=[a['extract_notes'] or f"Article {a['position']}: Generation is not complete yet." for a in all_rows if a['extract_notes'] or not a['headline'] or not a['body'] or a['id'] not in all_media]
                if failures:raise ValueError('\n'.join(failures))
                deck=build_deck(snapshot(iid),media(iid))
                with db() as c:
                    c.execute("UPDATE issues SET workflow_stage='owner_review',status='draft',generation_error='',content_revision=content_revision+1 WHERE id=?",(iid,))
                    i=c.execute('SELECT content_revision FROM issues WHERE id=?',(iid,)).fetchone()
                    c.execute('INSERT INTO generated_decks(issue_id,revision,payload) VALUES(?,?,?) ON CONFLICT(issue_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',(iid,i['content_revision'],base64.b64encode(deck).decode()))
                    save_version(c,iid,who,'Arabic slide draft generated')
                    c.execute('INSERT INTO audit(issue_id,action,actor,payload) VALUES(?,?,?,?)',(iid,'draft_ready',who,'{}'))
            except Exception as ex:
                with db() as c:c.execute("UPDATE issues SET workflow_stage='generation_failed',generation_error=? WHERE id=?",(str(ex)[:2500],iid))
            finally:
                with lock:active.discard(iid)

    @app.route('/issues/<int:iid>/generate-draft',methods=['POST'])
    def generate_draft(iid):
        require();i=issue(iid);check_edit(i,actor(),role())
        if i['workflow_stage'] not in ('draft','generation_failed','owner_review'):abort(409,'Draft generation is only available before the first approval.')
        if len(rows(iid))!=10:abort(400,'Exactly ten URLs are required.')
        if not os.getenv('OPENAI_API_KEY'):flash('AI generation is not configured. Add the generation API key in Render.','error');return redirect(url_for('view_issue',iid=iid))
        if not os.getenv('NEWSLETTER_TEMPLATE_KEY'):flash('The newsletter template is not configured.','error');return redirect(url_for('view_issue',iid=iid))
        with lock:
            if iid in active:abort(409,'Generation is already running.')
            active.add(iid)
        with db() as c:
            c.execute("UPDATE issues SET workflow_stage='generating',generation_error='' WHERE id=?",(iid,));audit(c,iid,None,'generation_started')
        retry_ids=None
        if i['workflow_stage']=='generation_failed':
            images=media(iid)
            retry_ids={a['id'] for a in rows(iid) if a['extract_notes'] or not a['headline'] or not a['body'] or a['id'] not in images}
        threading.Thread(target=run,args=(iid,actor(),retry_ids),daemon=True).start()
        flash('Generation started. Refresh this issue to follow progress.','success');return redirect(url_for('view_issue',iid=iid))


    @app.route('/articles/<int:aid>/retry-generation',methods=['POST'])
    def retry_article_generation(aid):
        require()
        with db() as c:
            article=c.execute('SELECT * FROM articles WHERE id=?',(aid,)).fetchone()
        if not article:abort(404)
        iid=article['issue_id'];i=issue(iid);check_edit(i,actor(),role())
        if i['workflow_stage']!='generation_failed' or not article['extract_notes']:
            abort(409,'Only a failed article can be retried. Wait for current generation to finish.')
        try:revision=int(request.form.get('article_revision','-1'))
        except ValueError:abort(400)
        if revision!=article['revision']:abort(409,'This article changed. Refresh before retrying.')
        text=request.form.get('original_text','').strip()
        title=request.form.get('original_title','').strip()
        if text and len(text)<200:
            flash('Paste at least 200 characters of the original article text.','error')
            return redirect(url_for('edit_article',aid=aid))
        if not text and len((article['supplied_content'] or article['source_text'] or '').strip())<200:
            flash('Paste the original article text before retrying this article.','error')
            return redirect(url_for('edit_article',aid=aid))
        if not os.getenv('OPENAI_API_KEY') or not os.getenv('NEWSLETTER_TEMPLATE_KEY'):
            flash('Generation credentials or template are not configured.','error')
            return redirect(url_for('edit_article',aid=aid))
        with lock:
            if iid in active:abort(409,'Generation is already running.')
            active.add(iid)
        try:
            with db() as c:
                cur=c.execute("UPDATE issues SET workflow_stage='generating',generation_error='',content_revision=content_revision+1 WHERE id=? AND workflow_stage='generation_failed' AND content_revision=?",(iid,i['content_revision']))
                if cur.rowcount!=1:abort(409,'This issue changed. Refresh before retrying.')
                if text:
                    cur=c.execute("UPDATE articles SET supplied_content=?,source_text=?,source_title=?,extract_status='supplied',revision=revision+1 WHERE id=? AND revision=?",(text,text,title or article['source_title'],aid,revision))
                    if cur.rowcount!=1:abort(409,'This article changed. Refresh before retrying.')
                c.execute('DELETE FROM generated_decks WHERE issue_id=?',(iid,))
                audit(c,iid,aid,'article_generation_retried',{'original_text_supplied':bool(text)})
            threading.Thread(target=run,args=(iid,actor(),{aid}),daemon=True).start()
        except BaseException:
            with lock:active.discard(iid)
            raise
        flash('Retry started for this article only. Other articles will not be regenerated.','success')
        return redirect(url_for('view_issue',iid=iid))

    @app.route('/issues/<int:iid>/assign',methods=['POST'])
    def assign_reviewers(iid):
        require();i=issue(iid)
        if role()!='admin' and actor()!=i['owner_email']:abort(403)
        if i['status']=='approved' or i['workflow_stage']=='generating':abort(409)
        values=[]
        for key in ('owner_email','reviewer_email','designer_email','final_email'):
            value=request.form.get(key,'').strip().casefold()
            if value and value not in people():abort(400,'Reviewers must already be authorized editorial users.')
            values.append(value)
        if not values[0]:abort(400,'Assign the first reviewer.')
        with db() as c:c.execute('UPDATE issues SET owner_email=?,reviewer_email=?,designer_email=?,final_email=? WHERE id=?',(*values,iid));audit(c,iid,None,'reviewers_assigned')
        flash('Reviewer assignments saved.','success');return redirect(url_for('view_issue',iid=iid))

    @app.route('/issues/<int:iid>/workflow-decision',methods=['POST'])
    def workflow_decision(iid):
        require();i=issue(iid);stage=i['workflow_stage']
        if stage not in STEPS:abort(409,'Generate the complete slide draft first.')
        if actor().casefold()!=i[ASSIGNEE[stage]].casefold():abort(403,'This newsletter is assigned to another reviewer.')
        try:revision=int(request.form.get('revision','-1'))
        except ValueError:abort(400)
        if revision!=i['content_revision']:abort(409,'The newsletter changed. Refresh and review the latest version.')
        decision=request.form.get('decision','');note=request.form.get('note','')[:2000]
        if decision not in ('approved','changes_requested'):abort(400)
        nextstage='owner_review' if decision=='changes_requested' else ('approved' if stage=='final_review' else STEPS[STEPS.index(stage)+1])
        if nextstage in ASSIGNEE and not i[ASSIGNEE[nextstage]]:flash('Assign the next reviewer before handing off.','error');return redirect(url_for('view_issue',iid=iid))
        if decision=='approved':
            aa=rows(iid)
            if len(aa)!=10 or any(not a['headline'] or not a['body'] for a in aa) or len(media(iid))!=10:abort(409,'Complete all ten slides before approval.')
            if stage=='design_review' and any(a['image_license_status']!='approved' for a in aa):flash('Confirm image rights for every article before approving the design.','error');return redirect(url_for('view_issue',iid=iid))
        snap=json.dumps(snapshot(iid),ensure_ascii=False) if nextstage=='approved' else None
        with db() as c:
            # Optimistic guard prevents double approvals and stale handoffs.
            cur=c.execute('UPDATE issues SET workflow_stage=?,status=?,approved_snapshot=?,approved_at=? WHERE id=? AND workflow_stage=? AND content_revision=? AND '+ASSIGNEE[stage]+'=?',(nextstage,'approved' if nextstage=='approved' else 'draft',snap,h['now']() if snap else None,iid,stage,revision,actor()))
            if cur.rowcount!=1:abort(409,'Another reviewer changed this issue. Refresh.')
            c.execute('INSERT INTO reviews(issue_id,stage,revision,reviewer,decision,note) VALUES(?,?,?,?,?,?)',(iid,stage,revision,actor(),decision,note))
            audit(c,iid,None,'workflow_handoff',{'from':stage,'to':nextstage})
        flash('Final newsletter approved and locked.' if snap else 'Newsletter sent to '+LABELS[nextstage]+'.','success');return redirect(url_for('view_issue',iid=iid))

    @app.route('/issues/<int:iid>/google-draft',methods=['POST'])
    def export_google_draft(iid):
        require();i=issue(iid)
        if i['workflow_stage'] not in STEPS:abort(409,'Generate the complete private draft first.')
        if actor()!=i[ASSIGNEE[i['workflow_stage']]]:abort(403)
        from google_publish import create_google_slides
        try:
            snap=snapshot(iid);deck=build_deck(snap,media(iid));url,id_=create_google_slides(snap,deck)
            with db() as c:
                c.execute('INSERT INTO publications(issue_id,kind,external_id,source_snapshot,status) VALUES(?,?,?,?,?)',(iid,'arabic_slides_draft',id_,json.dumps(snap,ensure_ascii=False),'private_draft'))
                audit(c,iid,None,'private_google_draft_created',{'revision':i['content_revision']})
            flash('Private Google Slides copy created: '+url,'success')
        except Exception:
            flash('Google Slides export failed. Confirm Google publishing is connected and Drive API is enabled for the OAuth project.','error')
        return redirect(url_for('view_issue',iid=iid))

    @app.route('/issues/<int:iid>/draft.pptx')
    def draft_deck(iid):
        require();i=issue(iid)
        if len(rows(iid))!=10:abort(409,'Create a new issue with ten URLs to use the integrated slide workflow.')
        if i['workflow_stage'] in ('draft','generating','generation_failed'):abort(409,'The complete slide draft is not ready.')
        with db() as c:stored=c.execute('SELECT * FROM generated_decks WHERE issue_id=?',(iid,)).fetchone()
        if not stored or stored['revision']!=i['content_revision']:
            data=build_deck(snapshot(iid),media(iid))
            with db() as c:c.execute('INSERT INTO generated_decks(issue_id,revision,payload) VALUES(?,?,?) ON CONFLICT(issue_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',(iid,i['content_revision'],base64.b64encode(data).decode()))
        else:data=base64.b64decode(stored['payload'])
        return send_file(io.BytesIO(data),as_attachment=True,download_name=f'AIW-AR{i["number"]}-v{i["content_revision"]}.pptx',mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation')

    @app.route('/articles/<int:aid>/preview-image')
    def workflow_image(aid):
        require()
        with db() as c:r=c.execute('SELECT payload FROM article_media WHERE article_id=?',(aid,)).fetchone()
        if not r:abort(404)
        return send_file(io.BytesIO(base64.b64decode(r['payload'])),mimetype='image/jpeg')

    @app.route('/issues/<int:iid>/versions')
    def version_history(iid):
        require();i=issue(iid)
        with db() as c:versions=c.execute('SELECT * FROM issue_versions WHERE issue_id=? ORDER BY id DESC',(iid,)).fetchall()
        return render_template('versions.html',i=i,versions=versions)

    @app.template_filter('fromjson')
    def fromjson(value):return json.loads(value)

    def can_edit(i):
        stage=i['workflow_stage']
        return (actor()==i['owner_email'] or role() in ('admin','coordinator')) if stage in ('draft','generation_failed') else (stage in ASSIGNEE and actor()==i[ASSIGNEE[stage]])

    def has_image(aid):
        with db() as c:return c.execute('SELECT article_id FROM article_media WHERE article_id=?',(aid,)).fetchone() is not None

    @app.context_processor
    def workflow_context():
        from google_publish import publishing_connected
        return {'google_publishing_connected':publishing_connected(actor()) if actor() else False,'generation_provider_ready':bool(os.getenv('OPENAI_API_KEY')),'workflow_labels':LABELS,'workflow_steps':STEPS,'assignee_fields':ASSIGNEE,'editorial_people':people(),'viewer_email':actor(),'can_edit_issue':can_edit,'has_article_image':has_image}

    app.logger.warning('Newsletter generation provider configured: %s; encrypted template configured: %s',bool(os.getenv('OPENAI_API_KEY')),bool(os.getenv('NEWSLETTER_TEMPLATE_KEY')))
    # A killed worker never masquerades as an indefinitely running job after restart.
    with db() as c:c.execute("UPDATE issues SET workflow_stage='generation_failed',generation_error='Generation was interrupted by a restart. Retry generation.' WHERE workflow_stage='generating'")
