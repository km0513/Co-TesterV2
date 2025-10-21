"""
API Co-Test Models
Database models for workspaces, environments, collections, and requests
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, ARRAY, Table, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

# db will be set by app.py after initialization
db = None

# Create a base class for models
Base = declarative_base()


class APIWorkspace(Base):
    __tablename__ = 'api_workspaces'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    user_id = Column(Integer)  # Will link to users table when auth is implemented
    is_team = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    environments = relationship('APIEnvironment', back_populates='workspace', cascade='all, delete-orphan')
    collections = relationship('APICollection', back_populates='workspace', cascade='all, delete-orphan')
    global_variables = relationship('APIGlobalVariable', back_populates='workspace', cascade='all, delete-orphan')
    history = relationship('APIRequestHistory', back_populates='workspace', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'user_id': self.user_id,
            'is_team': self.is_team,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class APIEnvironment(db.Model):
    __tablename__ = 'api_environments'
    
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('api_workspaces.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    workspace = relationship('APIWorkspace', back_populates='environments')
    variables = relationship('APIEnvironmentVariable', back_populates='environment', cascade='all, delete-orphan')
    
    def to_dict(self, include_variables=False):
        result = {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'name': self.name,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_variables:
            result['variables'] = [v.to_dict() for v in self.variables]
        return result


class APIEnvironmentVariable(db.Model):
    __tablename__ = 'api_environment_variables'
    
    id = Column(Integer, primary_key=True)
    environment_id = Column(Integer, ForeignKey('api_environments.id', ondelete='CASCADE'), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(Text)
    is_secret = Column(Boolean, default=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    environment = relationship('APIEnvironment', back_populates='variables')
    
    def to_dict(self, mask_secrets=True):
        return {
            'id': self.id,
            'environment_id': self.environment_id,
            'key': self.key,
            'value': '***HIDDEN***' if (self.is_secret and mask_secrets) else self.value,
            'is_secret': self.is_secret,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class APIGlobalVariable(db.Model):
    __tablename__ = 'api_global_variables'
    
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('api_workspaces.id', ondelete='CASCADE'), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(Text)
    is_secret = Column(Boolean, default=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    workspace = relationship('APIWorkspace', back_populates='global_variables')
    
    def to_dict(self, mask_secrets=True):
        return {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'key': self.key,
            'value': '***HIDDEN***' if (self.is_secret and mask_secrets) else self.value,
            'is_secret': self.is_secret,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class APICollection(db.Model):
    __tablename__ = 'api_collections'
    
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('api_workspaces.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    auth_type = Column(String(50))  # bearer, basic, oauth2, etc.
    auth_config = Column(JSONB)
    variables = Column(JSONB)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    workspace = relationship('APIWorkspace', back_populates='collections')
    folders = relationship('APICollectionFolder', back_populates='collection', cascade='all, delete-orphan')
    requests = relationship('APICollectionRequest', back_populates='collection', cascade='all, delete-orphan')
    
    def to_dict(self, include_requests=False):
        result = {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'name': self.name,
            'description': self.description,
            'auth_type': self.auth_type,
            'auth_config': self.auth_config,
            'variables': self.variables,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_requests:
            result['folders'] = [f.to_dict() for f in self.folders]
            result['requests'] = [r.to_dict() for r in self.requests]
        return result


class APICollectionFolder(db.Model):
    __tablename__ = 'api_collection_folders'
    
    id = Column(Integer, primary_key=True)
    collection_id = Column(Integer, ForeignKey('api_collections.id', ondelete='CASCADE'), nullable=False)
    parent_folder_id = Column(Integer, ForeignKey('api_collection_folders.id', ondelete='CASCADE'))
    name = Column(String(255), nullable=False)
    description = Column(Text)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    collection = relationship('APICollection', back_populates='folders')
    parent = relationship('APICollectionFolder', remote_side=[id], backref='subfolders')
    requests = relationship('APICollectionRequest', back_populates='folder')
    
    def to_dict(self):
        return {
            'id': self.id,
            'collection_id': self.collection_id,
            'parent_folder_id': self.parent_folder_id,
            'name': self.name,
            'description': self.description,
            'order_index': self.order_index,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class APICollectionRequest(db.Model):
    __tablename__ = 'api_collection_requests'
    
    id = Column(Integer, primary_key=True)
    collection_id = Column(Integer, ForeignKey('api_collections.id', ondelete='CASCADE'), nullable=False)
    folder_id = Column(Integer, ForeignKey('api_collection_folders.id', ondelete='CASCADE'))
    name = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    url = Column(Text, nullable=False)
    headers = Column(JSONB)
    body = Column(Text)
    body_type = Column(String(50))  # json, form, raw, etc.
    pre_request_script = Column(Text)
    test_script = Column(Text)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    collection = relationship('APICollection', back_populates='requests')
    folder = relationship('APICollectionFolder', back_populates='requests')
    
    def to_dict(self):
        return {
            'id': self.id,
            'collection_id': self.collection_id,
            'folder_id': self.folder_id,
            'name': self.name,
            'method': self.method,
            'url': self.url,
            'headers': self.headers,
            'body': self.body,
            'body_type': self.body_type,
            'pre_request_script': self.pre_request_script,
            'test_script': self.test_script,
            'order_index': self.order_index,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class APIRequestHistory(db.Model):
    __tablename__ = 'api_request_history'
    
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('api_workspaces.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer)
    method = Column(String(10), nullable=False)
    url = Column(Text, nullable=False)
    headers = Column(JSONB)
    body = Column(Text)
    response_status = Column(Integer)
    response_time = Column(Integer)  # in milliseconds
    response_body = Column(Text)
    response_headers = Column(JSONB)
    environment_id = Column(Integer, ForeignKey('api_environments.id', ondelete='SET NULL'))
    executed_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    workspace = relationship('APIWorkspace', back_populates='history')
    
    def to_dict(self):
        return {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'user_id': self.user_id,
            'method': self.method,
            'url': self.url,
            'headers': self.headers,
            'body': self.body,
            'response_status': self.response_status,
            'response_time': self.response_time,
            'response_body': self.response_body,
            'response_headers': self.response_headers,
            'environment_id': self.environment_id,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None
        }


class APIFavorite(db.Model):
    __tablename__ = 'api_favorites'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    request_id = Column(Integer)
    name = Column(String(255))
    tags = Column(ARRAY(String))
    method = Column(String(10), nullable=False)
    url = Column(Text, nullable=False)
    headers = Column(JSONB)
    body = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'request_id': self.request_id,
            'name': self.name,
            'tags': self.tags,
            'method': self.method,
            'url': self.url,
            'headers': self.headers,
            'body': self.body,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
