import time
from typing import Dict, List

from peewee import fn

import config
from model._post import POST_TYPES
from model.log_manage import ManageLog, MANAGE_OPERATION as MOP
from model.statistic import statistic_new
from model.wiki import WikiArticle
from slim.base.permission import Permissions, DataRecord
from slim.base.sqlquery import SQLValuesToWrite
from slim.retcode import RETCODE
from slim.support.peewee import PeeweeView
from view import route, cooldown, same_user, ValidateForm
from wtforms import validators as va, StringField, IntegerField
from permissions import permissions_add_all
from view.user import UserMixin


class WikiNewForm(ValidateForm):
    title = StringField('标题', validators=[
        va.required(),
        va.Length(config.POST_TITLE_LENGTH_MIN, config.POST_TITLE_LENGTH_MAX)
    ])

    content = StringField('正文', validators=[
        va.required(),
        va.Length(1, config.POST_CONTENT_LENGTH_MAX)
    ])


@route('wiki')
class WikiView(UserMixin, PeeweeView):
    """
    文档有一个简单的版本设定，但忽略任何并发导致的同步问题
    """
    model = WikiArticle

    @classmethod
    def ready(cls):
        cls.add_soft_foreign_key('id', 'statistic')
        cls.add_soft_foreign_key('user_id', 'user')

    @classmethod
    def permission_init(cls):
        permission: Permissions = cls.permission
        permissions_add_all(permission)

    @route.interface('GET')
    async def random(self):
        wa = WikiArticle.get_random_one()
        if wa:
            self.finish(RETCODE.SUCCESS, {'id': wa})
        else:
            self.finish(RETCODE.NOT_FOUND)

    @route.interface('POST')
    async def pick_version(self):
        pass

    @route.interface('POST')
    async def rollback(self):
        pass

    async def get(self):
        await super().get()
        if self.ret_val['code'] == RETCODE.SUCCESS:
            pass

    @cooldown(config.TOPIC_NEW_COOLDOWN_BY_IP, b'ic_cd_wiki_new_%b', cd_if_unsuccessed=10)
    @cooldown(config.TOPIC_NEW_COOLDOWN_BY_ACCOUNT, b'ic_cd_wiki_new_account_%b', unique_id_func=same_user, cd_if_unsuccessed=10)
    async def new(self):
        return await super().new()

    def after_read(self, records: List[DataRecord]):
        for i in records:
            pass

    async def before_insert(self, raw_post: Dict, values_lst: List[SQLValuesToWrite]):
        values = values_lst[0]
        form = WikiNewForm(**raw_post)
        if not form.validate():
            return self.finish(RETCODE.FAILED, form.errors)

        values['time'] = int(time.time())
        values['user_id'] = self.current_user.id

        root_id = values.get('root_id', None)
        if root_id:
            newest = WikiArticle.get_newest_by_root_id(root_id)
            if not newest:
                return self.finish(RETCODE.FAILED, '找不到对应的原始词条')
            values['major_ver'] = newest.major_ver
            # 这里忽略并发导致的 minor_ver 相同的问题，理论上发生率太低
            values['minor_ver'] = newest.minor_ver + 1
        else:
            values['is_current'] = True
            values['major_ver'] = 1
            values['minor_ver'] = 0

    def after_insert(self, raw_post: Dict, values: SQLValuesToWrite, records: List[DataRecord]):
        record = records[0]
        WikiArticle.update(root_id=record['id'])\
            .where(WikiArticle.id == record['id'], WikiArticle.minor_ver==0)\
            .execute()

        # 添加统计记录
        statistic_new(POST_TYPES.WIKI, record['id'])
