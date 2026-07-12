from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('competitors', '0010_landscapereport'),
    ]

    operations = [
        migrations.AddField(
            model_name='competitorsource',
            name='youtube_uploads_playlist',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
