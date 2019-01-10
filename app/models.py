from datetime import datetime
from hashlib import md5
from time import time
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from app import db, login
from app.search import add_to_index, remove_from_index, query_index
import array
arraytypecode = chr(ord('f'))


class SearchableMixin(object):
    @classmethod
    def search(cls, expression, page, per_page):
        ids, total = query_index(cls.__tablename__, expression, page, per_page)
        if total == 0:
            return cls.query.filter_by(id=0), 0
        when = []
        for i in range(len(ids)):
            when.append((ids[i], i))
        return cls.query.filter(cls.id.in_(ids)).order_by(
            db.case(when, value=cls.id)), total

    @classmethod
    def before_commit(cls, session):
        session._changes = {
            'add': [obj for obj in session.new if isinstance(obj, cls)],
            'update': [obj for obj in session.dirty if isinstance(obj, cls)],
            'delete': [obj for obj in session.deleted if isinstance(obj, cls)]
        }

    @classmethod
    def after_commit(cls, session):
        for obj in session._changes['add']:
            add_to_index(cls.__tablename__, obj)
        for obj in session._changes['update']:
            add_to_index(cls.__tablename__, obj)
        for obj in session._changes['delete']:
            remove_from_index(cls.__tablename__, obj)
        session._changes = None

    @classmethod
    def reindex(cls):
        for obj in cls.query:
            add_to_index(cls.__tablename__, obj)


followers = db.Table(
    'followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    about_me = db.Column(db.String(140))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')

    def __repr__(self):
        return '<User {}>'.format(self.username)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return 'https://www.gravatar.com/avatar/{}?d=identicon&s={}'.format(
            digest, size)

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

    def is_following(self, user):
        return self.followed.filter(
            followers.c.followed_id == user.id).count() > 0

    def followed_posts(self):
        followed = Post.query.join(
            followers, (followers.c.followed_id == Post.user_id)).filter(
                followers.c.follower_id == self.id)
        own = Post.query.filter_by(user_id=self.id)
        return followed.union(own).order_by(Post.timestamp.desc())

    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'],
            algorithm='HS256').decode('utf-8')

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                            algorithms=['HS256'])['reset_password']
        except:
            return
        return User.query.get(id)


@login.user_loader
def load_user(id):
    return User.query.get(int(id))


class Post(SearchableMixin, db.Model):
    __searchable__ = ['body']
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.String(140))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    language = db.Column(db.String(5))
    image = db.Column(db.LargeBinary)
    extension = db.Column(db.String(50))

    def __repr__(self):
        return '<Post {}>'.format(self.body)


db.event.listen(db.session, 'before_commit', Post.before_commit)
db.event.listen(db.session, 'after_commit', Post.after_commit)


class Samples(db.Model):
    sample_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    spectral_library = db.Column(db.String(256))
    class_mineral = db.Column(db.String)
    name = db.Column(db.String)
    image = db.Column(db.LargeBinary)
    image_link = db.Column(db.String)
    wavelength_range = db.Column(db.String(128))
    description = db.Column(db.TEXT)

    @staticmethod
    def get_classes():
        try:
            clsses = Samples.query.with_entities(Samples.class_mineral).distinct().all()
        except:
            return []
        return [cls[0] for cls in clsses]

    @staticmethod
    def get_names_by_class(cls):
        try:
            nms = Samples.query.filter(Samples.class_mineral == cls).with_entities(Samples.name).distinct().all()
        except:
            return []
        return [nm[0] for nm in nms]

    @staticmethod
    def get_sample_id_by_name(name):
        try:
            lst0 = Samples.query.filter(Samples.name.contains(name)).with_entities(Samples.sample_id).distinct().all()
            lst1 = Samples.query.filter(Samples.name.contains(name.lower())).with_entities(
                Samples.sample_id).distinct().all()
            lst2 = Samples.query.filter(Samples.name.contains(name.title())).with_entities(
                Samples.sample_id).distinct().all()
            lst = list(set().union(lst0, lst1, lst2))
        except:
            return []
        return [l[0] for l in lst]

    @staticmethod
    def get_spectra_metatadata_by_sample_id(iid):
        try:
            qr = Samples.query.filter(Samples.sample_id == iid).first()
            txt = "Name: " + qr.name + "\n" + \
                  "Class: " + qr.class_mineral + "\n" + \
                  "Wavelength range: " + qr.wavelength_range + "\n" + \
                  "Description: " + qr.description
        except:
            txt = []
        return txt

    @staticmethod
    def get_sample_image_from_id(iid):
        try:
            im = Samples.query.filter(Samples.sample_id == iid).with_entities(Samples.image).first()
        except:
            return None
        return im.image


class Spectra(db.Model):
    spectrum_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sample_id = db.Column(db.Integer, db.ForeignKey('samples.sample_id', ondelete='CASCADE'))
    instrument = db.Column(db.String(128))
    measurement = db.Column(db.String(128))
    x_unit = db.Column(db.String(128))
    y_unit = db.Column(db.String(128))
    min_wavelength = db.Column(db.Float)
    max_wavelength = db.Column(db.Float)
    num_values = db.Column(db.Integer)
    additional_information = db.Column(db.TEXT)
    x_data = db.Column(db.LargeBinary)
    y_data = db.Column(db.LargeBinary)
    sample = db.relationship("Samples", backref=db.backref("spectrum", passive_deletes=True, uselist=False))

    @staticmethod
    def get_spectrum_by_id(iid):
        try:
            dt = Spectra.query.filter(Spectra.sample_id == iid).with_entities(Spectra.x_data, Spectra.y_data).first()
            x = array.array(arraytypecode)
            x.frombytes(dt.x_data)
            y = array.array(arraytypecode)
            y.frombytes(dt.y_data)
        except:
            return []
        return [list(x), list(y)]