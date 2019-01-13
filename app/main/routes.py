from datetime import datetime
from flask import render_template, flash, redirect, url_for, request, g, \
    jsonify, current_app
from flask_login import current_user, login_required
from flask_babel import _, get_locale
from guess_language import guess_language
from app import db
from app.main.forms import EditProfileForm, PostForm, SearchForm, SpectraForm, AddSpectraForm
from app.models import User, Post
from app.models import Samples, Spectra
from app.translate import translate
from app.main import bp
from werkzeug.datastructures import CombinedMultiDict
from flask import Response
import os
import json
import plotly
import plotly.plotly as py
import plotly.graph_objs as go
import numpy as np
import pandas as pd
import io
import csv
import array
arraytypecode = chr(ord('f'))

basedir = os.path.abspath(os.path.dirname(__file__))

@bp.before_app_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
        g.search_form = SearchForm()
    g.locale = str(get_locale())


@bp.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    form = PostForm(CombinedMultiDict((request.files, request.form)))
    if form.validate_on_submit():
        language = guess_language(form.post.data)
        if language == 'UNKNOWN' or len(language) > 5:
            language = ''

        target = os.path.join(os.path.abspath(os.path.join(basedir,'..')), 'static')
        f = request.files.get('image', '')
        print("ha", f)
        if f == '':
            print("here")
            img = None
            extension = None
        else:
            f.save(os.path.join(target, f.filename))
            extension = f.filename
            img = f.read()
        post = Post(body=form.post.data, author=current_user,
                    language=language,image=img, extension=extension)
        db.session.add(post)
        db.session.commit()
        if f != '':
            f.save(os.path.join(target, str(post.id)+extension))
        flash(_('Your post is now live!'))
        return redirect(url_for('main.index'))
    page = request.args.get('page', 1, type=int)
    posts = current_user.followed_posts().paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.index', page=posts.next_num) \
        if posts.has_next else None
    prev_url = url_for('main.index', page=posts.prev_num) \
        if posts.has_prev else None
    return render_template('index.html', title=_('Home'), form=form,
                           posts=posts.items, next_url=next_url,
                           prev_url=prev_url)


@bp.route('/')
@bp.route('/explore')
def explore():
    page = request.args.get('page', 1, type=int)
    posts = Post.query.order_by(Post.timestamp.desc()).paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.explore', page=posts.next_num) \
        if posts.has_next else None
    prev_url = url_for('main.explore', page=posts.prev_num) \
        if posts.has_prev else None
    return render_template('explore.html', title=_('Explore'),
                           posts=posts.items, next_url=next_url,
                           prev_url=prev_url)


@bp.route('/user/<username>')
@login_required
def user(username):
    user = User.query.filter_by(username=username).first_or_404()
    page = request.args.get('page', 1, type=int)
    posts = user.posts.order_by(Post.timestamp.desc()).paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.user', username=user.username,
                       page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.user', username=user.username,
                       page=posts.prev_num) if posts.has_prev else None
    return render_template('user.html', user=user, posts=posts.items,
                           next_url=next_url, prev_url=prev_url)


@bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(current_user.username)
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.about_me = form.about_me.data
        db.session.commit()
        flash(_('Your changes have been saved.'))
        return redirect(url_for('main.edit_profile'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', title=_('Edit Profile'),
                           form=form)


@bp.route('/follow/<username>')
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash(_('User %(username)s not found.', username=username))
        return redirect(url_for('main.index'))
    if user == current_user:
        flash(_('You cannot follow yourself!'))
        return redirect(url_for('main.user', username=username))
    current_user.follow(user)
    db.session.commit()
    flash(_('You are following %(username)s!', username=username))
    return redirect(url_for('main.user', username=username))


@bp.route('/unfollow/<username>')
@login_required
def unfollow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash(_('User %(username)s not found.', username=username))
        return redirect(url_for('main.index'))
    if user == current_user:
        flash(_('You cannot unfollow yourself!'))
        return redirect(url_for('main.user', username=username))
    current_user.unfollow(user)
    db.session.commit()
    flash(_('You are not following %(username)s.', username=username))
    return redirect(url_for('main.user', username=username))


@bp.route('/translate', methods=['POST'])
@login_required
def translate_text():
    return jsonify({'text': translate(request.form['text'],
                                      request.form['source_language'],
                                      request.form['dest_language'])})


@bp.route('/search')
@login_required
def search():
    if not g.search_form.validate():
        return redirect(url_for('main.explore'))
    page = request.args.get('page', 1, type=int)
    posts, total = Post.search(g.search_form.q.data, page,
                               current_app.config['POSTS_PER_PAGE'])
    next_url = url_for('main.search', q=g.search_form.q.data, page=page + 1) \
        if total > page * current_app.config['POSTS_PER_PAGE'] else None
    prev_url = url_for('main.search', q=g.search_form.q.data, page=page - 1) \
        if page > 1 else None
    return render_template('search.html', title=_('Search'), posts=posts,
                           next_url=next_url, prev_url=prev_url)


@bp.route('/spectra', methods=['GET', 'POST'])
def spectra():
    form = SpectraForm()
    form.category.choices = [(cat, cat) for cat in sorted(Samples.get_classes())]
    form.matrname.choices = [(scls, scls) for scls in sorted(Samples.get_names_by_class(form.category.choices[0][0]))]
    form.smples.choices = [(smp, smp) for smp in sorted(Samples.get_sample_id_by_name(form.matrname.choices[0][0]))]
    form.description.data = Samples.get_spectra_metatadata_by_sample_id(form.smples.choices[0][0])

    dta = Spectra.get_spectrum_by_id(form.smples.choices[0][0])
    xScale = np.array(dta[0])
    yScale = np.array(dta[1])

    # Create a trace
    trace = go.Scatter(
        x=xScale,
        y=yScale,
        marker=dict(size=4)
    )

    data = [trace]
    graphJSON = json.dumps(data, cls=plotly.utils.PlotlyJSONEncoder)
    return render_template('spectra.html', graphJSON=graphJSON, form=form)


@bp.route('/matrname/<category>')
def matrname(category):
    matrnames = sorted(Samples.get_names_by_class(category))
    matrnamesArr =[]
    for i, mat in enumerate(matrnames):
        matObj = {}
        matObj['id'] = mat
        matObj['name'] = mat
        matrnamesArr.append(matObj)
    return jsonify({'matrnames': matrnamesArr})


@bp.route('/smple/<matrname>')
def smple(matrname):
    smples = sorted(Samples.get_sample_id_by_name(matrname))
    smplesArr =[]
    for i, smp in enumerate(smples):
        smpObj = {}
        smpObj['id'] = smp
        smpObj['name'] = smp
        smplesArr.append(smpObj)
    return jsonify({'smples': smplesArr})


@bp.route('/grph/<smple>')
def graph(smple):
    dta = Spectra.get_spectrum_by_id(smple)
    dsk = Samples.get_spectra_metatadata_by_sample_id(smple)
    dtaArray = []
    dtaObj = {}
    dtaObj['id'] = "x"
    dtaObj['val'] = dta[0]
    dtaArray.append(dtaObj)
    dtaObj = {}
    dtaObj['id'] = "y"
    dtaObj['val'] = dta[1]
    dtaArray.append(dtaObj)
    dtaObj = {}
    dtaObj['id'] = "dsc"
    dtaObj['val'] = dsk
    dtaArray.append(dtaObj)
    return jsonify({'grph': dtaArray})


@bp.route('/addspectra', methods=['GET', 'POST'])
@login_required
def addspectra():
    form = AddSpectraForm(CombinedMultiDict((request.files, request.form)))
    if form.validate_on_submit():
        fimg = request.files.get('image', '')
        fdata = request.files.get('datafile', '')
        stream = io.StringIO(fdata.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.reader(stream)
        xData = []
        yData = []
        for row in csv_input:
            xData.append(float(row[0]))
            yData.append(float(row[1]))
        xBlob = array.array(arraytypecode, xData).tostring()
        yBlob = array.array(arraytypecode, yData).tostring()
        name = form.name.data
        measurement = form.measurement.data
        spectrallib = form.spectrallib.data
        category = form.category.data
        description = form.description.data
        imagelink = form.imagelink.data
        wavelengthunit = form.wavelengthunit.data
        spectraunit = form.spectraunit.data

        sample = Samples(spectral_library=spectrallib, class_mineral=category, name=name, \
                           image=fimg.read(), image_link=imagelink, wavelength_range="vis", \
                           description=description)
        db.session.add(sample)
        db.session.commit()
        spectrum = Spectra(sample_id=sample.sample_id, instrument="ZUmicrospectrometer", \
                           measurement=measurement, x_unit=wavelengthunit, y_unit=spectraunit, \
                           min_wavelength=xData[0], max_wavelength=xData[-1], num_values=len(xData), \
                           additional_information=description, x_data=xBlob, y_data=yBlob)
        db.session.add(spectrum)
        db.session.commit()

    return render_template('addspectra.html', form=form)

